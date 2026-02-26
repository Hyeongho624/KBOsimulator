# 개선된 KBO 시뮬레이션 - 현실성 강화 v3
# 추가: 병살/희생타, 도루 고도화, 투수 피로도 능력 저하

import pandas as pd
import random
import multiprocessing as mp

# ========== 설정 파라미터 ==========
year_weights = {2025: 0.5, 2024: 0.35, 2023: 0.15}

# 투수 피로도 파라미터
PITCHER_FATIGUE_PARAMS = {
    "per_batter": 1.0,
    "per_hit": 1.5,
    "per_walk": 1.2,
    "per_run": 2.0,
    "high_stress": 0.8,
}

# 병살 확률 (주자 상황별)
DOUBLE_PLAY_PROB = {
    "runner_on_first": 0.12,  # 1루 주자만 있을 때
    "bases_loaded": 0.10,  # 만루
    "first_and_second": 0.11,  # 1,2루
    "first_and_third": 0.09  # 1,3루
}

# 희생플라이 확률 (3루 주자 있고 아웃카운트 < 2)
SAC_FLY_PROB = 0.035  # 타석당 약 3.5%

# 도루 상황별 가중치
STEAL_SITUATION_WEIGHTS = {
    "score_ahead": 0.3,  # 이기고 있을 때 (보수적)
    "score_close": 1.0,  # 1-2점차
    "score_behind": 1.3,  # 지고 있을 때 (공격적)
    "late_inning": 1.2,  # 7회 이후
    "two_outs": 0.4,  # 2아웃 (매우 보수적)
    "power_hitter": 0.5  # 강타자 타석 (홈런 기대)
}

# ========== 데이터 로딩 ==========
hitters_df = pd.read_csv("statiz_hitters.csv")
pitchers_df = pd.read_csv("statiz_pitchers.csv")
hitter_types_df = pd.read_csv("statiz_hitters_type.csv")
pitcher_types_df = pd.read_csv("statiz_pitchers_type.csv")

hitters_df[["K%", "BB%"]] /= 100.0
pitchers_df[["K%", "BB%"]] /= 100.0

hitter_hand_dict = dict(zip(hitter_types_df["Name"], hitter_types_df["Handedness"]))
pitcher_types = dict(zip(pitcher_types_df.index, pitcher_types_df["Pitching_Type"]))
hitters_by_player = {p: df for p, df in hitters_df.groupby("Player")}
pitchers_by_player = {p: df for p, df in pitchers_df.groupby("Player")}

# 도루 능력 매핑
steal_attempt_prob = {}
steal_success_prob = {}
for player, df in hitters_by_player.items():
    sb = df["SB"].mean()
    pa = df["PA"].mean()
    sb_pct = df["SB%"].mean() / 100.0 if "SB%" in df.columns else 0.7
    if pa and pa > 0 and not pd.isna(sb):
        steal_attempt_prob[player] = min(sb / pa, 0.15)
        steal_success_prob[player] = sb_pct if not pd.isna(sb_pct) else 0.7
    else:
        steal_attempt_prob[player] = 0.0
        steal_success_prob[player] = 0.0

def get_weighted_stat(player_data, column):
    """연도별 가중 평균"""
    total, weight_sum = 0, 0
    for _, row in player_data.iterrows():
        year = row["Year"]
        if year in year_weights and pd.notna(row[column]):
            total += year_weights[year] * float(row[column])
            weight_sum += year_weights[year]
    return total / weight_sum if weight_sum else 0.0

# 타자 장타력 매핑 (강타자 판별용)
hitter_power = {}
for player, df in hitters_by_player.items():
    slg = get_weighted_stat(df, "SLG") if "SLG" in df.columns else 0.4
    hitter_power[player] = slg

# 투수 능력치 사전 계산
pitcher_quality = {}
for player, df in pitchers_by_player.items():
    era = get_weighted_stat(df, "ERA") if "ERA" in df.columns else 4.5
    fip = get_weighted_stat(df, "FIP") if "FIP" in df.columns else 4.5
    quality = (era + fip) / 2
    pitcher_quality[player] = quality


def create_team(name, lineup, starter, bullpen, roles=None):
    """팀 생성"""
    default_roles = {
        "closer": bullpen[-1] if bullpen else None,
        "setup": bullpen[-2] if len(bullpen) > 1 else None,
        "long_relief": bullpen[:2] if len(bullpen) > 2 else [],
        "middle_relief": bullpen[2:-2] if len(bullpen) > 4 else bullpen[:-2] if len(bullpen) > 2 else [],
    }
    if roles:
        default_roles.update(roles)
    return {
        "name": name,
        "lineup": lineup,
        "starter": starter,
        "bullpen": bullpen,
        "roles": default_roles
    }


def calculate_pitcher_collapse(pitcher_name):
    """투수 컨디션 기반 붕괴"""
    if pitcher_name not in pitcher_quality:
        base_collapse_prob = 0.05
    else:
        quality = pitcher_quality[pitcher_name]
        if quality < 3.0:
            base_collapse_prob = 0.01
        elif quality < 3.5:
            base_collapse_prob = 0.02
        elif quality < 4.0:
            base_collapse_prob = 0.03
        elif quality < 5.0:
            base_collapse_prob = 0.05
        else:
            base_collapse_prob = 0.08
    return random.random() < base_collapse_prob


def calculate_pitcher_fatigue_penalty(pitcher_name, pitcher_fatigue):
    """
    투수 피로도에 따른 능력 저하
    에이스급: 100구까지 유지, 그 이후 저하
    평균급: 80구부터 저하
    약한 투수: 60구부터 저하

    returns: (k_rate_multiplier, bb_rate_multiplier, control_factor)
    """
    quality = pitcher_quality.get(pitcher_name, 4.5)

    # 투수 등급별 피로 시작점
    if quality < 3.0:  # 에이스
        fatigue_start = 100
        fatigue_severe = 120
    elif quality < 4.0:  # 평균 이상
        fatigue_start = 80
        fatigue_severe = 100
    else:  # 평균 이하
        fatigue_start = 60
        fatigue_severe = 80

    if pitcher_fatigue < fatigue_start:
        return 1.0, 1.0, 1.0  # 정상

    # 피로도 진행 비율
    if pitcher_fatigue < fatigue_severe:
        fatigue_ratio = (pitcher_fatigue - fatigue_start) / (fatigue_severe - fatigue_start)
    else:
        fatigue_ratio = 1.0 + (pitcher_fatigue - fatigue_severe) / 20.0
        fatigue_ratio = min(fatigue_ratio, 2.0)

    # 삼진율 감소 (10~30%)
    k_rate_mult = 1.0 - (0.3 * fatigue_ratio)

    # 볼넷 증가 (20~50%)
    bb_rate_mult = 1.0 + (0.5 * fatigue_ratio)

    # 제구력 저하 (타자 유리도)
    control_factor = 1.0 + (0.15 * fatigue_ratio)

    return max(0.7, k_rate_mult), min(1.5, bb_rate_mult), min(1.15, control_factor)


def precompute_hitter_stats(hitter_df, pitcher_type, pitcher_name, pitcher_fatigue, collapse=False):
    """타자 능력치 계산"""
    matchup_avg_key = "RAVG" if pitcher_type in ["우투", "우언"] else "LAVG"
    matchup_obp_key = "ROBP" if pitcher_type in ["우투", "우언"] else "LOBP"

    avg = get_weighted_stat(hitter_df, "AVG")
    obp = get_weighted_stat(hitter_df, "OBP")
    slg = get_weighted_stat(hitter_df, "SLG")
    wrc_plus = get_weighted_stat(hitter_df, "wRC+")

    matchup_avg = get_weighted_stat(hitter_df, matchup_avg_key)
    matchup_obp = get_weighted_stat(hitter_df, matchup_obp_key)

    babip = get_weighted_stat(hitter_df, "BABIP")
    k_rate = get_weighted_stat(hitter_df, "K%")
    bb_rate = get_weighted_stat(hitter_df, "BB%")

    condition = random.uniform(0.95, 1.05)
    wrc_factor = max(0.75, min(1.25, wrc_plus / 100.0)) if wrc_plus > 0 else 1.0

    hybrid_avg = (0.5 * avg + 0.35 * matchup_avg + 0.15 * babip) * condition * wrc_factor
    hybrid_obp = (0.5 * obp + 0.5 * matchup_obp) * condition * wrc_factor
    hybrid_slg = slg * condition * wrc_factor

    # 투수 피로도 페널티 적용
    k_mult, bb_mult, control_factor = calculate_pitcher_fatigue_penalty(pitcher_name, pitcher_fatigue)

    k_rate *= k_mult  # 투수 삼진율 감소
    bb_rate *= bb_mult  # 투수 볼넷 증가
    hybrid_avg *= control_factor  # 제구 흔들림
    hybrid_obp *= control_factor

    # 투수 붕괴
    if collapse:
        hybrid_avg *= 1.25
        hybrid_obp *= 1.25
        hybrid_slg *= 1.2
        bb_rate *= 1.3
        k_rate *= 0.6

    return hybrid_avg, hybrid_obp, hybrid_slg, k_rate, bb_rate


def get_base_situation_key(bases):
    """주자 상황을 키로 변환"""
    if bases[0] and bases[1] and bases[2]:
        return "bases_loaded"
    elif bases[0] and bases[1]:
        return "first_and_second"
    elif bases[0] and bases[2]:
        return "first_and_third"
    elif bases[0]:
        return "runner_on_first"
    else:
        return None


def attempt_double_play(bases, outs):
    """병살 시도"""
    if outs >= 2:  # 2아웃에는 병살 불가
        return False, 0

    situation_key = get_base_situation_key(bases)
    if situation_key is None:
        return False, 0

    dp_prob = DOUBLE_PLAY_PROB.get(situation_key, 0)

    if random.random() < dp_prob:
        # 병살 성공
        return True, 2

    return False, 0


def attempt_sacrifice_fly(bases, outs, hitter_slg):
    """희생플라이 시도 (3루 주자 있고 아웃카운트 < 2)"""
    if outs >= 2 or not bases[2]:
        return False

    # 장타력 있는 타자일수록 확률 증가
    adjusted_prob = SAC_FLY_PROB * (1 + (hitter_slg - 0.4) * 0.5)

    if random.random() < adjusted_prob:
        return True

    return False


def calculate_steal_probability(hitter, bases, outs, inning, score_diff, next_hitter_power):
    """상황별 도루 시도 확률 계산"""
    base_prob = steal_attempt_prob.get(hitter, 0)

    if base_prob == 0 or outs >= 2:
        return 0

    # 상황별 가중치
    weight = 1.0

    # 점수차
    if score_diff > 3:
        weight *= STEAL_SITUATION_WEIGHTS["score_ahead"]
    elif abs(score_diff) <= 2:
        weight *= STEAL_SITUATION_WEIGHTS["score_close"]
    elif score_diff < -2:
        weight *= STEAL_SITUATION_WEIGHTS["score_behind"]

    # 후반 이닝
    if inning >= 7:
        weight *= STEAL_SITUATION_WEIGHTS["late_inning"]

    # 2아웃
    if outs == 2:
        weight *= STEAL_SITUATION_WEIGHTS["two_outs"]

    # 다음 타자가 강타자면 도루 시도 감소
    if next_hitter_power > 0.5:
        weight *= STEAL_SITUATION_WEIGHTS["power_hitter"]

    return base_prob * weight


def attempt_steal(hitter, bases, outs, inning, score_diff, next_hitter):
    """고도화된 도루 시도"""
    if not bases[0] or bases[1]:
        return bases, False

    next_hitter_power = hitter_power.get(next_hitter, 0.4)
    steal_prob = calculate_steal_probability(hitter, bases, outs, inning, score_diff, next_hitter_power)

    if random.random() < steal_prob:
        success_prob = steal_success_prob.get(hitter, 0.7)
        if random.random() < success_prob:
            bases[0], bases[1] = False, True
        else:
            bases[0] = False
            return bases, True  # 도루 실패

    return bases, False


def update_pitcher_fatigue(defense_team, result, bases_before):
    """투수 피로도 업데이트"""
    current_pitcher = defense_team["current_pitcher"]
    fatigue = PITCHER_FATIGUE_PARAMS

    defense_team["pitcher_fatigue"][current_pitcher] += fatigue["per_batter"]

    if result in ["single", "double", "triple", "homerun"]:
        defense_team["pitcher_fatigue"][current_pitcher] += fatigue["per_hit"]
    elif result == "walk":
        defense_team["pitcher_fatigue"][current_pitcher] += fatigue["per_walk"]

    if bases_before[1] or bases_before[2]:
        defense_team["pitcher_fatigue"][current_pitcher] += fatigue["high_stress"]


def update_game_state(result, score, outs, bases, hitter, hitter_slg, defense_team, inning, score_diff, next_hitter):
    """게임 상태 업데이트 (병살, 희생플라이 포함)"""
    bases_before = bases.copy()

    if result == "strikeout":
        outs += 1

    elif result == "out":
        # 희생플라이 시도
        if attempt_sacrifice_fly(bases, outs, hitter_slg):
            score += 1
            bases[2] = False
            outs += 1
        else:
            # 일반 아웃 - 병살 시도
            is_dp, dp_outs = attempt_double_play(bases, outs)

            if is_dp:
                outs += dp_outs
                # 1루 주자 제거, 다른 주자는 진루 안함
                bases[0] = False
            else:
                outs += 1
                # 주자 진루 (확률적)
                if bases[2] and outs < 3 and random.random() < 0.15:
                    score += 1
                    bases[2] = False
                if bases[1] and not bases[2] and random.random() < 0.25:
                    bases[2], bases[1] = True, False

    elif result == "walk":
        if all(bases):
            score += 1
        if bases[0] and bases[1]:
            bases[2] = True
        if bases[0]:
            bases[1] = True
        bases[0] = True

    elif result == "single":
        runs = 0
        if bases[2]:
            runs += 1
        if bases[1] and random.random() < 0.30:
            runs += 1
            bases[1] = False
        score += runs
        bases = [True] + bases[:2]

    elif result == "double":
        runs = 0
        if bases[2]: runs += 1
        if bases[1]: runs += 1
        if bases[0] and random.random() < 0.40:
            runs += 1
        else:
            bases[2] = bases[0]
        score += runs
        bases = [False, True, bases[2] if bases[0] and random.random() >= 0.40 else False]

    elif result == "triple":
        score += sum(bases)
        bases = [False, False, True]

    elif result == "homerun":
        score += 1 + sum(bases)
        bases = [False, False, False]

    update_pitcher_fatigue(defense_team, result, bases_before)

    # 도루 시도
    if outs < 3:
        bases, steal_out = attempt_steal(hitter, bases, outs, inning, score_diff, next_hitter)
        if steal_out:
            outs += 1

    return score, outs, bases


def at_bat_result(avg, obp, slg, k_rate, bb_rate):
    """타석 결과"""
    r = random.random()

    if r < k_rate:
        return "strikeout"
    elif r < k_rate + bb_rate:
        return "walk"
    elif r < k_rate + bb_rate + obp:
        return determine_hit_type(avg, slg)
    else:
        return "out"


def determine_hit_type(avg, slg):
    """안타 종류 - ISO 기반"""
    iso = slg - avg

    if iso > 0.25:
        return random.choices(
            ["single", "double", "triple", "homerun"],
            weights=[55, 25, 5, 15]
        )[0]
    elif iso > 0.18:
        return random.choices(
            ["single", "double", "triple", "homerun"],
            weights=[60, 25, 5, 10]
        )[0]
    elif iso > 0.12:
        return random.choices(
            ["single", "double", "homerun"],
            weights=[70, 23, 7]
        )[0]
    else:
        return random.choices(
            ["single", "double", "homerun"],
            weights=[80, 17, 3]
        )[0]


def get_leverage_situation(inning, score_diff, outs, bases):
    """레버리지 상황 판단"""
    if inning >= 9:
        if 0 < score_diff <= 3:
            return "save"
        elif score_diff == 0:
            return "high"
        elif -3 <= score_diff < 0:
            return "high"

    if inning >= 7:
        if abs(score_diff) <= 2:
            return "medium"

    if abs(score_diff) >= 5:
        return "garbage"

    return "low"


def choose_relief_pitcher(defense_team, offense_team, inning, score_diff, outs, bases):
    """투수 교체 로직"""
    current_pitcher = defense_team["current_pitcher"]
    current_fatigue = defense_team["pitcher_fatigue"].get(current_pitcher, 0)
    is_starter = (current_pitcher == defense_team["starter"])

    roles = defense_team["roles"]
    bullpen = defense_team["bullpen"]

    if is_starter:
        runs_allowed = defense_team.get("starter_runs_allowed", 0)

        if current_fatigue < 90 and runs_allowed <= 3:
            return current_pitcher

        if runs_allowed >= 5 and current_fatigue >= 60:
            long_relievers = roles.get("long_relief", [])
            available_long = [p for p in long_relievers if defense_team["pitcher_fatigue"].get(p, 0) < 40]
            if available_long:
                return available_long[0]

        if current_fatigue >= 90:
            pass
        else:
            return current_pitcher

    leverage = get_leverage_situation(inning, score_diff, outs, bases)

    if leverage == "save":
        closer = roles.get("closer")
        if closer and defense_team["pitcher_fatigue"].get(closer, 0) < 20:
            return closer

    if inning == 8 and 0 < score_diff <= 3:
        setup = roles.get("setup")
        if setup and defense_team["pitcher_fatigue"].get(setup, 0) < 20:
            return setup

    if leverage == "garbage":
        available = [p for p in bullpen if defense_team["pitcher_fatigue"].get(p, 0) < 35]
        if available:
            worst_pitcher = max(available, key=lambda p: pitcher_quality.get(p, 5.0))
            return worst_pitcher

    if leverage == "high":
        available = [p for p in bullpen if defense_team["pitcher_fatigue"].get(p, 0) < 20]
        if available:
            best_pitcher = min(available, key=lambda p: pitcher_quality.get(p, 5.0))
            return best_pitcher

    middle = roles.get("middle_relief", [])
    available_middle = [p for p in middle if defense_team["pitcher_fatigue"].get(p, 0) < 25]

    if available_middle:
        next_hitters = [
            offense_team["lineup"][i % 9]
            for i in range(offense_team["batter_index"], offense_team["batter_index"] + 3)
        ]
        return choose_best_matchup(available_middle, next_hitters)

    available_any = [p for p in bullpen if defense_team["pitcher_fatigue"].get(p, 0) < 30]
    if available_any:
        return available_any[0]

    return current_pitcher


def choose_best_matchup(pitchers, next_hitters):
    """매치업 기반 최적 투수"""
    best_pitcher = None
    best_score = float('inf')

    for p in pitchers:
        p_type = pitcher_types.get(p, "우투")
        total_avg = 0

        for h in next_hitters:
            if h in hitters_by_player:
                stats = precompute_hitter_stats(hitters_by_player[h], p_type, p, 0)
                total_avg += stats[0]

        if total_avg < best_score:
            best_score = total_avg
            best_pitcher = p

    return best_pitcher if best_pitcher else pitchers[0]


def simulate_inning(offense_team, defense_team, inning, score_diff):
    """이닝 시뮬레이션"""
    score, outs = 0, 0
    bases = [False, False, False]

    current_pitcher = choose_relief_pitcher(
        defense_team, offense_team, inning, score_diff, outs, bases
    )
    defense_team["current_pitcher"] = current_pitcher

    pitcher_collapsed = calculate_pitcher_collapse(current_pitcher)
    p_type = pitcher_types.get(current_pitcher, "우투")

    while outs < 3:
        hitter = offense_team["lineup"][offense_team["batter_index"] % 9]
        next_hitter = offense_team["lineup"][(offense_team["batter_index"] + 1) % 9]
        offense_team["batter_index"] += 1

        pitcher_fatigue = defense_team["pitcher_fatigue"].get(current_pitcher, 0)

        stats = precompute_hitter_stats(
            hitters_by_player[hitter],
            p_type,
            current_pitcher,
            pitcher_fatigue,
            pitcher_collapsed
        )

        result = at_bat_result(*stats)

        score_before = score
        score, outs, bases = update_game_state(
            result, score, outs, bases, hitter, stats[2], defense_team, inning, score_diff, next_hitter
        )

        if current_pitcher == defense_team["starter"]:
            runs_this_ab = score - score_before
            defense_team["starter_runs_allowed"] = defense_team.get("starter_runs_allowed", 0) + runs_this_ab

    return score


def simulate_game(_=None):
    """경기 시뮬레이션"""
    team_A = create_team(
        "KIA",
        ["박찬호", "오선우", "김도영", "최형우", "김선빈", "이우성", "한준수", "김호령", "최원준"],
        "네일",
        ["김기훈", "김현수", "성영탁", "윤중현", "이준영", "장재혁", "전상현", "조상우", "정해영"],
        roles={
            "closer": "전상현",
            "setup": "조상우",
            "long_relief": ["김기훈", "김현수"],
            "middle_relief": ["성영탁", "윤중현", "이준영", "장재혁", "정해영"]
        }
    )

    team_B = create_team(
        "KT",
        ["황재균", "김민혁", "안현민", "장성우", "로하스", "강백호", "김상수", "문상철", "박민석"],
        "조이현",
        ["김민수", "김재원", "문용익", "손동현", "우규민", "원상현", "주권", "박영현"],
        roles={
            "closer": "박영현",
            "setup": "주권",
            "long_relief": ["김민수", "김재원"],
            "middle_relief": ["문용익", "손동현", "우규민", "원상현"]
        }
    )

    t1 = {
        **team_A,
        "batter_index": 0,
        "pitcher_fatigue": {p: 0 for p in [team_A["starter"]] + team_A["bullpen"]},
        "current_pitcher": team_A["starter"],
        "starter_runs_allowed": 0
    }

    t2 = {
        **team_B,
        "batter_index": 0,
        "pitcher_fatigue": {p: 0 for p in [team_B["starter"]] + team_B["bullpen"]},
        "current_pitcher": team_B["starter"],
        "starter_runs_allowed": 0
    }

    score1 = score2 = 0

    for inning in range(1, 10):
        score_diff = score1 - score2
        score1 += simulate_inning(t1, t2, inning, score_diff)

        score_diff = score2 - score1
        score2 += simulate_inning(t2, t1, inning, score_diff)

    if score1 == score2:
        for inning in range(10, 13):
            score_diff = score1 - score2
            score1 += simulate_inning(t1, t2, inning, score_diff)

            score_diff = score2 - score1
            score2 += simulate_inning(t2, t1, inning, score_diff)

            if score1 != score2:
                break

    return score1, score2


if __name__ == "__main__":
    match_count = 100

    print("=== KBO 시뮬레이션 시작 ===")
    print(f"총 {match_count}경기 시뮬레이션 중...\n")

    with mp.Pool() as pool:
        results = pool.map(simulate_game, range(match_count))

    t1w = t2w = draw = total1 = total2 = 0
    score_distribution = {"low": 0, "mid": 0, "high": 0}

    for s1, s2 in results:
        total1 += s1
        total2 += s2
        total_runs = s1 + s2

        if total_runs < 6:
            score_distribution["low"] += 1
        elif total_runs < 12:
            score_distribution["mid"] += 1
        else:
            score_distribution["high"] += 1

        if s1 > s2:
            t1w += 1
        elif s2 > s1:
            t2w += 1
        else:
            draw += 1

    avg1 = total1 / match_count
    avg2 = total2 / match_count

    print("=== 시뮬레이션 결과 ===")
    print(f"{'KIA':<10} 평균 득점: {avg1:.2f} | 승: {t1w}")
    print(f"{'KT':<10} 평균 득점: {avg2:.2f} | 승: {t2w}")
    print(f"무승부: {draw}")
    print("\n득점 분포:")
    print(f" - 저득점 경기(<6): {score_distribution['low']}회")
    print(f" - 중간득점 경기(6~11): {score_distribution['mid']}회")
    print(f" - 다득점 경기(12+): {score_distribution['high']}회")

    win_rate = t1w / match_count
    print(f"\nKIA 승률: {win_rate:.3f}")
    print(f"KT 승률: {1 - win_rate:.3f}")
