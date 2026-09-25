# Zellovest

Monorepo containing both the Python Data Science / ML backend and the Next.js frontend.

## Folder Structure

This is just give me an idea about folder structure, not exactly how it needs to be

```text
zellovest/
│
├── backend/                    <-- Python, Data Science, ML & API service (managed by uv)
│   ├── data/                   <-- Datasets (ignored in Git)
│   │   ├── raw/                <-- Original, immutable data
│   │   └── processed/          <-- Cleaned, feature-engineered data
│   │
│   ├── notebooks/              <-- Jupyter notebooks for exploration & prototyping
│   │   ├── 01_eda.ipynb        <-- Exploratory Data Analysis
│   │   └── 02_model_baseline.ipynb
│   │
│   ├── src/                    <-- Reusable package and API code
│   │   └── zellovest/          <-- Python package
│   │       ├── __init__.py     <-- Package initializer
│   │       ├── api/            <-- REST API routes (FastAPI server for Next.js)
│   │       │   └── main.py
│   │       ├── config.py       <-- Constants, paths, hyperparameters
│   │       ├── data_loader.py  <-- Data ingestion functions
│   │       ├── preprocessing.py<-- Feature engineering & cleaning
│   │       ├── train.py        <-- Training routines
│   │       └── predict.py      <-- Model inference pipeline
│   │
│   ├── tests/                  <-- Pytest unit & integration tests
│   │   └── test_preprocessing.py
│   │
│   ├── models/                 <-- Saved model artifacts (.pkl, .onnx, etc.)
│   │
│   ├── pyproject.toml          <-- uv project configuration & dependencies
│   ├── uv.lock                 <-- Locked dependency versions
│   └── .python-version         <-- Pinned Python version (3.13)
│
├── frontend/                   <-- Next.js React application (managed by npm/pnpm)
│   ├── public/                 <-- Static assets (logos, images, icons)
│   ├── src/                    <-- Frontend source code
│   │   ├── app/                <-- Next.js App Router (pages & layouts)
│   │   ├── components/         <-- Reusable UI components
│   │   ├── lib/                <-- API client & utilities (fetches from Python backend)
│   │   └── styles/             <-- Global styles
│   │
│   ├── package.json            <-- Frontend dependencies & scripts
│   ├── tsconfig.json           <-- TypeScript configuration
│   └── next.config.mjs         <-- Next.js configuration
│
├── .gitignore                  <-- Ignores .venv/, node_modules/, data/, models/
└── README.md                   <-- Project documentation & setup instructions
```