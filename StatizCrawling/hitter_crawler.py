import os
import time
import random
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# === 설정 ===
CHROMEDRIVER_PATH = "C:/Users/user/Downloads/chromedriver-win64/chromedriver.exe"
OUTPUT_PATH = "statiz_hitters.csv"

YEARS = [2023, 2024, 2025]
TEAMS = {
    "5002": "LG", "1001": "삼성", "9002": "SSG", "3001": "롯데", "12001": "KT",
    "6002": "두산", "7002": "한화", "10001": "키움", "2002": "KIA", "11001": "NC"
}
PITCHER_TYPES = {
    "R": ["RAVG", "ROBP", "RSLG"],
    "L": ["LAVG", "LOBP", "LSLG"],
    "2": ["UAVG", "UOBP", "USLG"]
}
COLUMNS = ["Year", "Team", "Player", "PA", "AVG", "OBP", "SLG", "wRC+",
           "K%", "BB%", "BABIP", "SB RAA", "SB", "SB%",
           "RAVG", "ROBP", "RSLG", "LAVG", "LOBP", "LSLG", "UAVG", "UOBP", "USLG"]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Safari/605.1.15"
]

# === 유틸리티 함수 ===
def wait(min_sec=3, max_sec=6):
    time.sleep(random.uniform(min_sec, max_sec))

def setup_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
    return webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)

def is_blocked(driver):
    return "403 Forbidden" in driver.page_source

def select_team(driver, team_code):
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#select_team > button"))).click()
    wait()
    team_option = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, f"#select_team ul.option_list > li.option_item[value='{team_code}']"))
    )
    driver.execute_script("arguments[0].click();", team_option)
    wait(3, 5)

def get_table_soup(driver):
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.table_type01 table")))
    return BeautifulSoup(driver.page_source, "html.parser").select_one("div.table_type01 table")

def switch_tab(driver, tab_value):
    driver.execute_script(f"$('#m3').val('{tab_value}'); searchStats('so|ob');")
    wait(2, 4)

# === 크롤링 함수 ===
def collect_stats():
    all_data = []

    for year in YEARS:
        for team_code, team_name in TEAMS.items():
            try:
                driver = setup_driver()
                base_stats, pitcher_stats = {}, {}

                # 기본 성적
                driver.get(f"https://statiz.co.kr/stats/?m=main&m2=batting&reg=A&year={year}")

                wait()
                if is_blocked(driver): raise Exception("403 BLOCKED")

                select_team(driver, team_code)
                if is_blocked(driver): raise Exception("403 BLOCKED")

                for row in get_table_soup(driver).select("tbody tr"):
                    cols = row.find_all("td")
                    if len(cols) < 32: continue
                    name = cols[1].text.strip()
                    base_stats[name] = [cols[7].text.strip(), cols[26].text.strip(), cols[27].text.strip(),
                                        cols[28].text.strip(), cols[31].text.strip()]

                # 심화 성적
                switch_tab(driver, 'deepen')
                for row in get_table_soup(driver).select("tbody tr"):
                    cols = row.find_all("td")
                    if len(cols) < 8: continue
                    name = cols[1].text.strip()
                    if name in base_stats:
                        base_stats[name] += [cols[4].text.strip(), cols[5].text.strip(), cols[7].text.strip()]

                # 주루 성적
                switch_tab(driver, 'sb')
                for row in get_table_soup(driver).select("tbody tr"):
                    cols = row.find_all("td")
                    if len(cols) < 9: continue
                    name = cols[1].text.strip()
                    if name in base_stats:
                        base_stats[name] += [cols[5].text.strip(), cols[6].text.strip(), cols[8].text.strip()]

                # 투수 유형별 성적
                for pt_code, labels in PITCHER_TYPES.items():
                    driver.get(f"https://statiz.co.kr/stats/?m=main&m2=batting&year={year}&reg=A&pt={pt_code}")
                    wait(3, 6)
                    if is_blocked(driver): continue 

                    select_team(driver, team_code)

                    for row in get_table_soup(driver).select("tbody tr"):
                        cols = row.find_all("td")
                        if len(cols) < 25: continue
                        name = cols[1].text.strip()
                        if name not in pitcher_stats:
                            pitcher_stats[name] = {}
                        pitcher_stats[name][labels[0]] = cols[22].text.strip()
                        pitcher_stats[name][labels[1]] = cols[23].text.strip()
                        pitcher_stats[name][labels[2]] = cols[24].text.strip()

                # 데이터 병합
                for name, values in base_stats.items():
                    row = [year, team_name, name] + values
                    for pt in PITCHER_TYPES:
                        for label in PITCHER_TYPES[pt]:
                            row.append(pitcher_stats.get(name, {}).get(label, ""))
                    if len(row) == len(COLUMNS):
                        all_data.append(row)

                print(f"{year}년 {team_name} 성공")
                driver.quit()
                wait(20, 40)

            except Exception as e:
                print(f"{year}년 {team_name} 실패: {e}")
                try: driver.quit()
                except: pass
                wait(40, 60)
    
    return all_data

# === 실행 ===
if __name__ == "__main__":
    print("KBO 타자 세부 성적 수집 시작")

    result = collect_stats()

    valid_data = [row for row in result if len(row) == len(COLUMNS)]
    if len(valid_data) < len(result):
        print(f"유효하지 않은 행 {len(result) - len(valid_data)}개 제외")

    pd.DataFrame(valid_data, columns=COLUMNS).to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print("KBO 타자 세부 성적 수집 완료")