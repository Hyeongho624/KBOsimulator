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

CHROMEDRIVER_PATH = "C:/Users/user/Downloads/chromedriver-win64/chromedriver.exe"
OUTPUT_PATH = "statiz_pitchers.csv"

YEARS = [2023, 2024, 2025]
TEAMS = {
    "5002": "LG", "1001": "삼성", "9002": "SSG", "3001": "롯데", "12001": "KT",
    "6002": "두산", "7002": "한화", "10001": "키움", "2002": "KIA", "11001": "NC"
}
BATTER_TYPES = {
    "1": ["V_R_ERA", "V_R_WHIP", "V_R_AVG", "V_R_OBP"],
    "2": ["V_L_ERA", "V_L_WHIP", "V_L_AVG", "V_L_OBP"]
}
COLUMNS = [
    "Year", "Team", "Player", "G", "W", "L", "IP", "ERA", "FIP", "WHIP",
    "K%", "BB%", "HR/9", "BABIP"
] + [col for values in BATTER_TYPES.values() for col in values]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Safari/605.1.15"
]

def wait(min_sec=3, max_sec=6):
    time.sleep(random.uniform(min_sec, max_sec))

def setup_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
    return webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)

def get_table_soup(driver):
    WebDriverWait(driver, 15).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "div.table_type01 table"))
    )
    return BeautifulSoup(driver.page_source, "html.parser").select_one("div.table_type01 table")

def select_team(driver, team_code):
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#select_team > button"))).click()
    wait()
    team_option = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, f"#select_team ul.option_list > li.option_item[value='{team_code}']"))
    )
    driver.execute_script("arguments[0].click();", team_option)
    wait(3, 5)

def set_all_pa(driver):
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#select_reg > button"))).click()
    wait()
    all_option = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "#select_reg ul.option_list > li.option_item[value='A']"))
    )
    driver.execute_script("arguments[0].click();", all_option)
    wait(3, 5)

def collect_pitcher_stats():
    all_data = []

    for year in YEARS:
        for team_code, team_name in TEAMS.items():
            try:
                driver = setup_driver()
                pitcher_stats = {}

                # 기본 성적 탭
                driver.get(f"https://statiz.co.kr/stats/?m=main&m2=pitching&reg=A&year={year}")
                wait()
                select_team(driver, team_code)
                for row in get_table_soup(driver).select("tbody tr"):
                    cols = row.find_all("td")
                    if len(cols) < 36: continue
                    name = cols[1].text.strip()
                    pitcher_stats[name] = [cols[i].text.strip() for i in [4, 10, 11, 14, 30, 34, 35]]

                # 심화 탭: K%, BB%, HR/9, BABIP
                driver.get(f"https://statiz.co.kr/stats/?m=main&m2=pitching&m3=deepen&year={year}&reg=A")
                wait()
                select_team(driver, team_code)
                for row in get_table_soup(driver).select("tbody tr"):
                    cols = row.find_all("td")
                    if len(cols) < 13: continue
                    name = cols[1].text.strip()
                    if name in pitcher_stats:
                        pitcher_stats[name] += [cols[i].text.strip() for i in [9, 10, 8, 12]]

                # 상황별 우/좌타자 상대 성적
                for bt_code, labels in BATTER_TYPES.items():
                    driver.get(f"https://statiz.co.kr/stats/?m=main&m2=pitching&m3=situation1&year={year}&reg=A&pt={bt_code}")
                    wait()
                    select_team(driver, team_code)
                    set_all_pa(driver)
                    for row in get_table_soup(driver).select("tbody tr"):
                        cols = row.find_all("td")
                        if len(cols) < 22: continue
                        name = cols[1].text.strip()
                        if name in pitcher_stats:
                            pitcher_stats[name] += [cols[i].text.strip() for i in [3, 19, 20, 21]]

                for name, stats in pitcher_stats.items():
                    row = [year, team_name, name] + stats
                    if len(row) == len(COLUMNS):
                        all_data.append(row)

                print(f"{year}년 {team_name} 성공")
                driver.quit()
                wait(20, 40)

            except Exception as e:
                print(f"{year}년 {team_name} 실패: {type(e).__name__} - {str(e)}")
                try: driver.quit()
                except: pass
                wait(40, 60)

    return all_data

if __name__ == "__main__":
    print("KBO 투수 성적 수집 시작")
    result = collect_pitcher_stats()

    valid_data = [row for row in result if len(row) == len(COLUMNS)]
    if len(valid_data) < len(result):
        print(f"유효하지 않은 행 {len(result) - len(valid_data)}개 제외")

    pd.DataFrame(valid_data, columns=COLUMNS).to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print("KBO 투수 성적 수집 완료")
