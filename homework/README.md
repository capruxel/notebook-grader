# 課程資料結構

這份文件說明 `nbgrader --course-root /path/to/course` 所讀取的**外部課程目錄**；此 repo 的 `homework/` 只存放本說明，請勿將學生名冊、作業或成績放進此 repo。

```text
/path/to/course/
├── docs/
│   └── 26_pattern-recognition_students-list.csv   # 名冊；可用 --roster 改相對路徑
├── homework/
│   ├── w1/                                     # 週次；介面會列出其子目錄
│   │   ├── w1_title.ipynb                      # 作業說明（供程式比較）
│   │   ├── D1234567.ipynb                      # 學生 notebook
│   │   └── D2345678/
│   │       └── answer.ipynb                    # 巢狀 notebook 也會找到
│   └── w2/
│       └── ...
└── submission/
    └── w1/
        └── scores.csv                          # 儲存成績後才建立
```

名冊是 UTF-8 CSV（可含 BOM），至少需要 `姓名,學號` 欄；例如：

```csv
姓名,學號
甲同學,D1234567
乙同學,D2345678
```

`homework/` 下每個子目錄是一個可選週次，週次內遞迴搜尋 `.ipynb`。檔案或其子目錄的名稱須包含**唯一一個名冊學號**，才能自動對應學生；學號格式為 `D` 加七位數字。只有 notebook 內容不含其他名冊學號時才會對應成功。姓名或僅出現在內容中的學號是候選線索，不能單獨決定歸屬；衝突或同一學生有多份 notebook 時，請在介面中人工覆核。其他檔案也列在檔案清單，但只有 `.ipynb` 可預覽。

`*_title.ipynb` 是作業說明，不參與學生配對；**程式比較**需要該週根目錄恰好一份這種檔案。Notebook 必須能解析為 JSON，且有 `cells` 清單；預覽只讀取已儲存的儲存格、輸出，不執行程式。

儲存分數時，程式建立或更新 `submission/<week>/scores.csv`，欄位為 `姓名,學號,成績,備註`，每位名冊學生一列；分數可為空白或 `0`–`100`（允許小數）。尚未儲存的預設 `0` 只是介面顯示，不會自動寫檔。
