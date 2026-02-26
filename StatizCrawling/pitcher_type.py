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
OUTPUT_PATH = "statiz_pitchers_type.csv"
YEARS = (2023, 2025)
TEAMS = {
    "5002": "LG", "1001": "삼성", "9002": "SSG", "3001": "롯데", "12001": "KT",
    "6002": "두산", "7002": "한화", "10001": "키움", "2002": "KIA", "11001": "NC"
}
HAND_MAP = {"R": "우투", "L": "좌투", "2": "우언"}
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Safari/605.1.15"
]

# === 유틸리티 함수 ===
def wait(min_sec=2, max_sec=4):
    time.sleep(random.uniform(min_sec, max_sec))

def setup_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
    return webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)

def get_table(driver):
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div.table_type01 table"))
    )
    html = driver.find_element(By.CSS_SELECTOR, "div.table_type01 table").get_attribute("outerHTML")
    return BeautifulSoup(html, "html.parser")

# === 크롤링 함수 ===
def crawl_pitcher_types():
    data = []
    url_template = (
        "https://statiz.co.kr/stats/?m=total&m2=pitching&m3=default"
        "&sy={sy}&ey={ey}&te={team}&reg=A&pl={pl}"
    )

    for team_code, team_name in TEAMS.items():
        pitcher_map = {}
        for pl_code, pitch_type in HAND_MAP.items():
            try:
                url = url_template.format(sy=YEARS[0], ey=YEARS[1], team=team_code, pl=pl_code)
                driver = setup_driver()
                driver.get(url)
                wait()

                soup = get_table(driver)
                for row in soup.select("tbody tr"):
                    cols = row.find_all("td")
                    if len(cols) < 3:
                        continue
                    name = cols[1].text.strip()
                    team_info = cols[2].text.strip()
                    if "P" not in team_info:
                        continue
                    # 우언이면 기존 값을 덮어씀
                    pitcher_map[name] = [name, team_name, team_info, pitch_type]

                print(f"{team_name} {pitch_type} 크롤링 성공")
                driver.quit()
                wait(2, 4)

            except Exception as e:
                print(f"{team_name} {pitch_type} 크롤링 실패: {e}")
                try: driver.quit()
                except: pass
                wait(5, 8)

        data.extend(pitcher_map.values())

    return data

# === 실행 ===
if __name__ == "__main__":
    print("KBO 투수 유형(우투/좌투/우언) 크롤링 시작")
    result = crawl_pitcher_types()
    df = pd.DataFrame(result, columns=["Name", "Team", "Team_Info", "Pitching_Type"])
    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print("KBO 투수 유형 크롤링 완료")
