# NoosphereBot — Pipeline Schema

> Full algorithm from user input to database and back.
> GitHub renders Mermaid diagrams natively — view this file on GitHub to see the visual.

---

## Full Message Pipeline

```mermaid
flowchart TD
    %% ── Input sources ──────────────────────────────────────────
    TG_USER("👤 User\nTelegram")
    WEB_USER("👤 User\nBrowser")

    %% ── Telegram path ───────────────────────────────────────────
    TG_USER -->|"sends message"| TG_SERVERS["Telegram Servers"]
    TG_SERVERS -->|"long polling\nevery ~1 s"| HANDLER["telegram_handler.py\nhandle_message()"]

    HANDLER --> STAGE1{"Stage 1\nKeyword match?"}

    STAGE1 -->|"'tasks', 'done N'\n'del N', 'add X: Y'"| FAST["Fast path\nno LLM"]
    STAGE1 -->|"natural language\nno match"| THINKING["reply '...'"]

    THINKING --> NLP["Ollama NLP\nqwen3.5:0.8b\n_parse_with_ollama()"]
    NLP -->|"JSON result\n{action, group, title, task_id}"| ROUTER["Action router"]
    FAST --> ROUTER

    %% ── Web path ────────────────────────────────────────────────
    WEB_USER -->|"POST /noosphere/add\nPOST /noosphere/complete\nPOST /noosphere/delete"| ROUTES["noosphere/routes.py\nFlask Blueprint"]
    ROUTES --> ROUTER

    %% ── CRUD layer ──────────────────────────────────────────────
    ROUTER -->|"action = add"| ADD["add_task(group, title)"]
    ROUTER -->|"action = summary/list"| LIST["list_tasks()\npending_summary()"]
    ROUTER -->|"action = complete"| COMPLETE["complete_task(id)"]
    ROUTER -->|"action = delete"| DELETE["delete_task(id)"]
    ROUTER -->|"action = unknown"| FALLBACK["Reply: help message"]

    %% ── Database ────────────────────────────────────────────────
    ADD --> DB[("SQLite\nbothub.db\ntasks table")]
    LIST --> DB
    COMPLETE --> DB
    DELETE --> DB

    %% ── Response ────────────────────────────────────────────────
    DB -->|"result"| FORMAT["Format response"]
    FALLBACK --> FORMAT

    FORMAT -->|"Telegram: reply_text()\nMarkdown"| TG_SERVERS
    TG_SERVERS -->|"delivers message"| TG_USER

    FORMAT -->|"Flask: redirect()\nrender_template()"| WEB_UI["noosphere.html\nTask dashboard"]
    WEB_UI --> WEB_USER

    %% ── Styling ─────────────────────────────────────────────────
    style DB         fill:#e8f4e8,stroke:#276749,color:#000
    style NLP        fill:#fff3cd,stroke:#f0c040,color:#000
    style TG_SERVERS fill:#e8f0fe,stroke:#1a56db,color:#000
    style WEB_UI     fill:#e8f0fe,stroke:#1a56db,color:#000
    style HANDLER    fill:#fce8e8,stroke:#c53030,color:#000
    style ROUTES     fill:#fce8e8,stroke:#c53030,color:#000
```

---

## Startup Sequence

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant AppPy as app.py (main)
    participant Werkzeug as Flask/Werkzeug (child)
    participant TGThread as Telegram thread (daemon)
    participant DB as SQLite

    Dev->>AppPy: python app.py
    AppPy->>AppPy: load_dotenv(.env)
    AppPy->>AppPy: import Blueprints
    AppPy->>DB: init_db() — create tables if missing
    AppPy->>Werkzeug: app.run(debug=True) — forks child
    Note over Werkzeug: WERKZEUG_RUN_MAIN = "true"
    Werkzeug->>TGThread: threading.Thread(start_telegram_bot)
    TGThread->>TGThread: asyncio.run(_run())
    TGThread-->>Dev: [Telegram] Bot online — polling
    Werkzeug-->>Dev: Running on http://127.0.0.1:5000
```

---

## Task Groups & Routing

```mermaid
flowchart LR
    MSG["Incoming message"] --> MATCH{"Group\ndetected?"}

    MATCH -->|"email / prof / send"| G2["📧 Emails to Send"]
    MATCH -->|"apply / cv / job / company"| G3["💼 Job Applications"]
    MATCH -->|"thesis / phd / supervisor"| G2b["🎓 PhD Applications"]
    MATCH -->|"read / paper / survey / slam"| G5["🔬 Research"]
    MATCH -->|"code / build / debug / flask"| G4["💻 Code Sessions"]
    MATCH -->|"idea / experiment / try"| G6["🚀 Crazy Projects"]
    MATCH -->|"no match → default"| G1["📅 Daily"]

    G1 & G2 & G2b & G3 & G4 & G5 & G6 --> CRUD["noosphere_bot.py\nadd_task(group, title)"]
    CRUD --> DB[("SQLite")]
```

---

## BotHub Platform Architecture

```mermaid
flowchart TD
    subgraph Flask["Flask app (app.py)"]
        DASH["/ dashboard"]
        LIT_BP["literature Blueprint\n/academibot\n/arxiv  /semantic\n/ieee  /openalex\n/merge  /litreview\n/problemmap"]
        NS_BP["noosphere Blueprint\n/noosphere\n/noosphere/add\n/noosphere/complete\n/noosphere/delete"]
    end

    subgraph Core["core/"]
        CFG["config.py\nshared paths"]
        OLL["ollama.py\ncheck_status()\nget_models()"]
        DB2["database.py\ninit_db()\nget_connection()"]
    end

    subgraph LitBots["bots/literature/"]
        ARXIV["arxiv_bot.py"]
        S2["semantic_scholar_bot.py"]
        IEEE["ieee_bot.py"]
        OA["openalex_bot.py"]
        MERGE["merge_bot.py"]
        LR["lit_review_bot.py"]
        PM["problem_map_bot.py"]
    end

    subgraph NSBots["bots/noosphere/"]
        NSB["noosphere_bot.py\nCRUD layer"]
        TGH["telegram_handler.py\nkeyword + Ollama NLP"]
    end

    subgraph Storage["Storage (repo root, gitignored)"]
        JSON["*.json files\nresults, merged,\nproblem_map"]
        SQLITE[("bothub.db\ntasks table")]
        PDFS["papers/\nPDF files"]
    end

    DASH --> LIT_BP & NS_BP
    LIT_BP --> LitBots
    NS_BP --> NSBots
    LitBots --> Core
    NSBots --> Core
    LitBots --> JSON & PDFS
    NSBots --> SQLITE
    TGH -.->|"daemon thread\n(started by app.py)"| NSB

    OLL -.->|"localhost:11434"| OLLAMA_SRV(["Ollama server"])
    LR & PM & TGH --> OLLAMA_SRV

    style OLLAMA_SRV fill:#fff3cd,stroke:#f0c040,color:#000
    style SQLITE     fill:#e8f4e8,stroke:#276749,color:#000
    style JSON       fill:#e8f4e8,stroke:#276749,color:#000
    style PDFS       fill:#e8f4e8,stroke:#276749,color:#000
```
