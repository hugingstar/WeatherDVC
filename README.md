# 🌦️ WeatherMLOps: 실시간 날씨 데이터 수집 파이프라인 & DVC 버전 관리 시스템

> **1분 간격 전국 실시간 날씨 데이터 수집**, **PostgreSQL 기반 고성능 데이터 저장소 및 커넥션 풀링**, **DVC(Data Version Control) 기반 데이터 버저닝 및 품질 검증**, **매일 00:00 자정 무중단 일일 분석 보고서 자동화**, 그리고 **통합 모니터링 웹 대시보드**를 제공하는 엔터프라이즈급 MLOps 데이터 파이프라인 프로젝트입니다.

---

## 🏗️ 시스템 아키텍처 (System Architecture)

```mermaid
flowchart TD
    %% Multi-Region Data Sources
    subgraph Data_Sources ["🌐 기상 데이터 소스 (Open-Meteo API)"]
        Loc1["서울 (Seoul)"]
        Loc2["광주 (Gwangju)"]
        Loc3["목포 (Mokpo)"]
        Loc4["부산 (Busan)"]
        Loc5["대구 / 대전 / 인천 / 제주 / 강릉 등"]
    end

    %% Ingestion Layer
    subgraph Ingestion_Layer ["⚡ 실시간 수집 레이어 (무중단 1분 주기)"]
        Collector["실시간 비동기 수집 엔진<br/>(src/collector.py / aiohttp)"]
        DB[("🐘 PostgreSQL Database<br/>(weather_db / Port: 5432)<br/>*ThreadedConnectionPool*")]
    end

    %% DVC Pipeline
    subgraph DVC_Pipeline ["📦 DVC 데이터 파이프라인 (dvc.yaml)"]
        Stage1["1. Preprocess (데이터 정제 & 파생변수 생성)<br/>src/pipeline/preprocess.py"]
        Stage2["2. Quality Check (품질 검증 & 이상치 탐지)<br/>src/pipeline/quality_check.py"]
        Stage3["3. Analyze & Report (시계열 분석 & 리포트 빌드)<br/>src/pipeline/report_generator.py"]
        
        Out_Processed["data/processed/<br/>- weather_all_regions.parquet<br/>- by_region/{city}.parquet"]
        Out_Metrics["metrics/<br/>- quality_summary.json<br/>- quality_{city}.json"]
        Out_Reports["reports/<br/>- daily_YYYY-MM-DD_overall.html<br/>- latest.html"]
    end

    %% Automation Layer
    subgraph Scheduler_Layer ["⏱️ 무중단 스케줄러 레이어"]
        Scheduler["BackgroundScheduler (APScheduler)<br/>매일 00:00:00 KST 트리거<br/>(src/scheduler.py)"]
    end

    %% Web Presentation Layer
    subgraph Web_Layer ["🖥️ 웹 모니터링 대시보드 (FastAPI)"]
        Server["FastAPI Web Server (src/web/app.py)<br/>REST API & WebSocket Engine"]
        UI["프리미엄 다크모드 웹 대시보드<br/>- 실시간 거점별 기상 카드<br/>- 1분 스트림 차트 (Chart.js)<br/>- 이력 테이블 & CSV 다운로드<br/>- DVC 일일 분석 보고서 뷰어"]
    end

    %% Connections
    Data_Sources -->|1분 주기 비동기 호출| Collector
    Collector -->|Batch Insert & Connection Pool| DB

    Scheduler -->|매일 자정 00:00 스냅샷 추출| Stage1
    DB -.->|원천 데이터 스냅샷| Stage1

    Stage1 --> Out_Processed
    Out_Processed --> Stage2
    Stage2 --> Out_Metrics
    Stage2 --> Stage3
    Stage3 --> Out_Reports

    DB -->|실시간 이력 및 최신 관측치 조회| Server
    Out_Metrics -->|품질 메트릭 서빙| Server
    Out_Reports -->|일일 분석 보고서 서빙| Server
    Server --> UI
```

---

## 🗄️ 데이터베이스 ER 다이어그램 (Entity-Relationship Diagram)

```mermaid
erDiagram
    LOCATION_CONFIG ||--o{ WEATHER_RECORDS : "1분 주기 관측 수집"
    DAILY_SNAPSHOTS ||--o{ WEATHER_RECORDS : "일일 원천 데이터 스냅샷 추출"
    WEATHER_RECORDS ||--o{ DVC_PROCESSED_DATA : "DVC 전처리 & 파생변수 생성"

    LOCATION_CONFIG {
        string id PK "지점 식별자 (예: seoul, gangneung)"
        string name "지점 한글명"
        string name_en "지점 영문명"
        int asos_code "기상청 ASOS 지점코드 (예: 108)"
        string region_group "기후/지리 권역 그룹"
        float latitude "관측 위도"
        float longitude "관측 경도"
        boolean enabled "수집 활성화 여부"
    }

    WEATHER_RECORDS {
        serial id PK "레코드 고유 일련번호"
        timestamptz timestamp "기상 관측 일시 (KST, 인덱스)"
        varchar location_id FK "관측 지점 ID (인덱스)"
        varchar location_name "지점 한글명"
        double latitude "위도"
        double longitude "경도"
        double temperature "기온 (℃)"
        double relative_humidity "상대습도 (%)"
        double wind_speed "풍속 (m/s)"
        double wind_direction "풍향 (°)"
        double precipitation "강수량 (mm)"
        double surface_pressure "해면기압 (hPa)"
        integer weather_code "WMO 날씨 코드"
        double apparent_temperature "체감온도 (℃)"
        timestamptz collected_at "데이터 수집 적재 일시 (KST)"
        varchar source "데이터 소스 (Open-Meteo)"
    }

    DAILY_SNAPSHOTS {
        serial id PK "스냅샷 고유 ID"
        varchar snapshot_date UK "스냅샷 기준 날짜 (YYYY-MM-DD)"
        integer total_records "스냅샷 총 레코드 수"
        text export_path "원천 CSV 내보내기 경로"
        timestamptz created_at "스냅샷 생성 시각 (KST)"
        varchar status "DVC 파이프라인 처리 상태"
    }

    DVC_PROCESSED_DATA {
        string timestamp PK "시계열 정렬 타임스탬프 (KST)"
        string location_id PK "지점 식별자"
        double temperature "결측 보정 기온 (℃)"
        double relative_humidity "결측 보정 습도 (%)"
        double discomfort_index "불쾌지수 (DI 파생변수)"
        double wind_chill "체감온도 (Wind Chill 파생변수)"
        double temp_roll_mean_15m "15분 이동평균 기온"
        string quality_status "DVC Z-Score 이상치 검증 플래그"
    }
```

---

## 🌟 주요 기능 (Key Features)

### 1. 전국 다중 거점 1분 실시간 비동기 수집 & PostgreSQL 저장
- **대상 지역**: 서울, 광주, 목포, 부산, 대구, 대전, 인천, 제주, 강릉 등 전국 주요 거점
- **수집 주기**: 1분 (60초) 비동기 병렬 호출 (`aiohttp`)
- **데이터베이스**: **PostgreSQL 16** (스레드 세이프 커넥션 풀링 `psycopg2.pool.ThreadedConnectionPool`, 인덱싱 및 원자적 트랜잭션 적용)
- **수집 항목**: 기온(℃), 상대습도(%), 풍속(m/s), 풍향(°), 해면기압(hPa), 강수량(mm), 체감온도(℃), 날씨코드

### 2. DVC (Data Version Control) 파이프라인
- **`preprocess`**: PostgreSQL에서 당일 데이터 스냅샷을 추출하여 결측치 보정, 불쾌지수(DI), 체감온도(Wind Chill), 15분 이동평균 생성 후 전국 통합 및 지역별 Parquet/CSV 저장
- **`quality_check`**: 1,440분 기준 결측률 검사, Z-Score 이상치 탐지, 기상 물리적 범위 위반 검사 후 `metrics/quality_summary.json` 지표 산출
- **`analyze_report`**: 시계열 추이, 지역별 Boxplot, 상관분석 히트맵을 생성하여 인터랙티브 HTML 일일 보고서 빌드
- `dvc repro` 및 `dvc metrics show` 명령을 통해 데이터 파이프라인 재현 및 품질 추적

### 3. 매일 00:00 자정 무중단 자동화 스케줄러
- `APScheduler` 기반으로 매일 자정 00:00:00(KST)에 실시간 수집을 중단하지 않고 전일 24시간치 스냅샷을 기반으로 DVC 파이프라인을 자동 구동

### 4. 통합 모니터링 웹 대시보드 (FastAPI)
- **실시간 날씨 현황 카드**: 서울, 광주, 목포 등 탭 클릭 시 해당 지역 기상 정보 즉시 표시
- **1분 실시간 스트림 차트**: Chart.js 기반 기온/습도 실시간 그래프
- **수집 이력 조회 & 검색**: 지역별/일시별 필터링 및 **CSV 원클릭 다운로드** 지원
- **DVC 보고서 뷰어**: 자정마다 자동 생성된 분석 보고서를 웹 상에서 모달 미리보기 및 새 창으로 열람 가능
- **수동 제어**: 상단 버튼으로 '즉시 수집' 및 'DVC 파이프라인 즉시 실행' 지원

---

## 📁 프로젝트 디렉터리 구조

```text
WeatherMLOps/
├── .dvc/                       # DVC 설정 및 메타데이터
├── data/
│   ├── raw/                    # PostgreSQL 추출 원천 데이터 일일 스냅샷 (DVC 추적)
│   └── processed/              # 정제된 Parquet/CSV 데이터 (전국 및 지역별)
│       └── by_region/          # 지역별 Parquet 파일 (seoul.parquet, gwangju.parquet 등)
├── metrics/                    # DVC 품질 메트릭 (quality_summary.json 등)
├── reports/                    # 자동 생성된 일일 분석 보고서 HTML
├── src/
│   ├── config.py               # 설정 로더
│   ├── db.py                   # PostgreSQL 커넥션 풀링 및 쿼리 모듈
│   ├── collector.py            # 1분 실시간 비동기 다중 거점 수집기
│   ├── scheduler.py            # 00:00 자정 무중단 스케줄러
│   ├── seed_data.py            # 24시간 모의/초기 데이터 시드 생성기
│   ├── pipeline/
│   │   ├── preprocess.py       # 전처리 및 파생변수 생성
│   │   ├── quality_check.py    # 데이터 품질 검증 및 이상치 탐지
│   │   └── report_generator.py # 인터랙티브 HTML 분석 보고서 빌더
│   └── web/
│       ├── app.py              # FastAPI 서버 & REST API
│       ├── static/             # CSS & JavaScript (Chart.js 연동)
│       └── templates/          # 대시보드 Jinja2 HTML 템플릿
├── config.yaml                 # PostgreSQL 연결 정보, 지역 좌표, 수집 주기 설정
├── docker-compose.yml          # PostgreSQL 컨테이너 구성 파일
├── dvc.yaml                    # DVC 파이프라인 스테이지 정의
├── requirements.txt            # 의존성 패키지 목록
└── README.md                   # 프로젝트 문서
```

---

## 🚀 빠른 시작 가이드 (Quick Start)

### 1. PostgreSQL 컨테이너 실행
```bash
docker compose up -d
```

### 2. 가상환경 구성 및 패키지 설치
```bash
# 가상환경 생성
python -m venv .venv

# 가상환경 활성화 (Windows PowerShell)
.venv\Scripts\Activate.ps1

# 의존성 설치
pip install -r requirements.txt
```

### 3. DVC 초기화
```bash
git init
dvc init
```

### 4. 초기 시드 데이터 생성 (선택 사항)
```bash
python -m src.seed_data
```

### 5. 웹 대시보드 및 백그라운드 수집기 실행
```bash
python -m uvicorn src.web.app:app --host 0.0.0.0 --port 8000
```
- 브라우저에서 **`http://localhost:8000`** 으로 접속합니다.
- 서버 실행 시 **1분 주기 실시간 수집기**와 **자정 00:00 스케줄러**가 자동으로 함께 시작됩니다.

---

## 📊 DVC 명령어 가이드

```bash
# 1. DVC 파이프라인 전체 스테이지 실행 (전처리 -> 품질검증 -> 리포트 생성)
dvc repro

# 2. 데이터 품질 메트릭 확인
dvc metrics show

# 3. 특정 스테이지 파이프라인 상태 점검
dvc status
```

---

## ⚙️ 설정 파일 (`config.yaml`)

```yaml
collection:
  interval_seconds: 60  # 1분 단위 수집

storage:
  type: "postgresql"
  postgres:
    host: "127.0.0.1"
    port: 5432
    user: "weather_user"
    password: "weather_password"
    dbname: "weather_db"

locations:
  - id: "seoul"
    name: "서울"
    latitude: 37.5665
    longitude: 126.9780
    enabled: true
  - id: "gwangju"
    name: "광주"
    latitude: 35.1595
    longitude: 126.8526
    enabled: true
  - id: "mokpo"
    name: "목포"
    latitude: 34.8118
    longitude: 126.3922
    enabled: true

quality_thresholds:
  expected_records_per_day: 1440
  min_completeness_ratio: 0.95
  z_score_threshold: 3.5

scheduler:
  daily_report_cron: "0 0 * * *" # 매일 00:00:00 (자정)
```
