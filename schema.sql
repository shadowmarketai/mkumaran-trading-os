-- ============================================================
-- MKUMARAN Hybrid Trading OS - PostgreSQL Schema
-- ============================================================

-- 1. WATCHLIST
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS watchlist (
    id          SERIAL        PRIMARY KEY,
    ticker      VARCHAR(20)   NOT NULL,
    name        VARCHAR(50),
    exchange    VARCHAR(10)   DEFAULT 'NSE',
    asset_class VARCHAR(15)   DEFAULT 'EQUITY',
    timeframe   VARCHAR(10)   DEFAULT 'day',
    tier        INTEGER       DEFAULT 2,
    ltrp        DECIMAL(10,2),
    pivot_high  DECIMAL(10,2),
    active      BOOLEAN       DEFAULT TRUE,
    source      VARCHAR(20)   DEFAULT 'manual',
    added_at    TIMESTAMP     DEFAULT NOW(),
    added_by    VARCHAR(20)   DEFAULT 'user',
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS idx_watchlist_ticker ON watchlist(ticker);
CREATE INDEX IF NOT EXISTS idx_watchlist_exchange ON watchlist(exchange);

-- 2. SIGNALS
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signals (
    id              SERIAL        PRIMARY KEY,
    signal_date     DATE          NOT NULL,
    signal_time     TIME,
    ticker          VARCHAR(20),
    exchange        VARCHAR(10)   DEFAULT 'NSE',
    asset_class     VARCHAR(15)   DEFAULT 'EQUITY',
    direction       VARCHAR(10),
    pattern         VARCHAR(50),
    entry_price     DECIMAL(10,2),
    stop_loss       DECIMAL(10,2),
    target          DECIMAL(10,2),
    rrr             DECIMAL(5,2),
    qty             INTEGER,
    risk_amt        DECIMAL(10,2),
    ai_confidence   INTEGER,
    tv_confirmed    BOOLEAN       DEFAULT FALSE,
    mwa_score       VARCHAR(10),
    scanner_count   INTEGER,
    tier            INTEGER,
    source          VARCHAR(20),
    timeframe       VARCHAR(10)   DEFAULT '1D',
    status          VARCHAR(20)   DEFAULT 'OPEN'
);

CREATE INDEX IF NOT EXISTS idx_signals_signal_date ON signals(signal_date);
CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);

-- 3. OUTCOMES
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS outcomes (
    id          SERIAL        PRIMARY KEY,
    signal_id   INTEGER       REFERENCES signals(id),
    exit_date   DATE,
    exit_price  DECIMAL(10,2),
    outcome     VARCHAR(10),
    pnl_amount  DECIMAL(10,2),
    days_held   INTEGER,
    exit_reason VARCHAR(20)
);

-- 4. MWA_SCORES
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mwa_scores (
    id               SERIAL        PRIMARY KEY,
    score_date       DATE          NOT NULL UNIQUE,
    direction        VARCHAR(15),
    bull_score       DECIMAL(5,1),
    bear_score       DECIMAL(5,1),
    bull_pct         DECIMAL(5,1),
    bear_pct         DECIMAL(5,1),
    scanner_results  JSONB,
    promoted_stocks  TEXT[],
    fii_net          DECIMAL(12,2),
    dii_net          DECIMAL(12,2),
    sector_strength  JSONB
);

CREATE INDEX IF NOT EXISTS idx_mwa_scores_score_date ON mwa_scores(score_date);

-- 5. ACTIVE_TRADES
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS active_trades (
    id              SERIAL        PRIMARY KEY,
    signal_id       INTEGER       REFERENCES signals(id),
    ticker          VARCHAR(20),
    exchange        VARCHAR(10)   DEFAULT 'NSE',
    asset_class     VARCHAR(15)   DEFAULT 'EQUITY',
    entry_price     DECIMAL(10,2),
    target          DECIMAL(10,2),
    stop_loss       DECIMAL(10,2),
    prrr            DECIMAL(5,2),
    current_price   DECIMAL(10,2),
    crrr            DECIMAL(5,2),
    last_updated    TIMESTAMP,
    timeframe       VARCHAR(10)   DEFAULT '1D',
    alert_sent      BOOLEAN       DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_active_trades_ticker ON active_trades(ticker);

-- ============================================================
-- SEED DATA: 29 Watchlist Stocks
-- ============================================================
INSERT INTO watchlist (ticker, name, timeframe, tier, ltrp, pivot_high, active, source, added_by) VALUES
('NSE:RELIANCE',   'Reliance Industries',    'day', 2, 1217.55,  1608.80, true, 'manual', 'system'),
('NSE:ACC',         'ACC Ltd',                'day', 2, 1903.05,  2844.45, true, 'manual', 'system'),
('NSE:SBIN',        'State Bank of India',    'day', 2,  720.55,   912.10, true, 'manual', 'system'),
('NSE:CDSL',        'CDSL',                   'day', 2, 1161.30,  1989.95, true, 'manual', 'system'),
('NSE:CENTURYTEX',  'Century Textiles',       'day', 2, 1725.00,  3043.50, true, 'manual', 'system'),
('NSE:GUJGASLTD',   'Gujarat Gas',            'day', 2,  353.10,   750.50, true, 'manual', 'system'),
('NSE:JINDALSTEL',  'Jindal Steel',           'day', 2,  592.40,  1097.90, true, 'manual', 'system'),
('NSE:BAJAJ-AUTO',  'Bajaj Auto',             'day', 2, 8186.00, 12774.00, true, 'manual', 'system'),
('NSE:BHARATFORG',  'Bharat Forge',           'day', 2, 1056.80,  1804.00, true, 'manual', 'system'),
('NSE:ECLERX',      'eClerx Services',        'day', 2, 2500.00,  3930.70, true, 'manual', 'system'),
('NSE:SHYAMMETL',   'Shyam Metalics',         'day', 2,  477.50,   960.45, true, 'manual', 'system'),
('NSE:TATASTEEL',   'Tata Steel',             'day', 2,  128.40,   184.60, true, 'manual', 'system'),
('NSE:ABCAPITAL',   'Aditya Birla Capital',   'day', 2,  165.30,   250.90, true, 'manual', 'system'),
('NSE:ABFRL',       'Aditya Birla Fashion',   'day', 2,  250.00,   349.30, true, 'manual', 'system'),
('NSE:CASTROLIND',  'Castrol India',          'day', 2,  195.50,   284.40, true, 'manual', 'system'),
('NSE:GMRINFRA',    'GMR Infrastructure',     'day', 2,   71.00,    98.60, true, 'manual', 'system'),
('NSE:PEL',         'Piramal Enterprises',    'day', 2,  825.00,  1216.65, true, 'manual', 'system'),
('NSE:LICHSGFIN',   'LIC Housing Finance',    'day', 2,  545.00,   833.00, true, 'manual', 'system'),
('NSE:BEL',         'Bharat Electronics',     'day', 2,  260.00,   340.35, true, 'manual', 'system'),
-- Sideways/watch stocks (NULL LTRP/pivot - auto-detect via swing_detector.py)
('NSE:TANLA',       'Tanla Platforms',        'day', 2,   NULL,     NULL,  true, 'manual', 'system'),
('NSE:IRCTC',       'IRCTC',                  'day', 2,   NULL,     NULL,  true, 'manual', 'system'),
('NSE:IDEA',        'Vodafone Idea',          'day', 2,   NULL,     NULL,  true, 'manual', 'system'),
('NSE:IRB',         'IRB Infrastructure',     'day', 2,   NULL,     NULL,  true, 'manual', 'system'),
('NSE:NBCC',        'NBCC India',             'day', 2,   NULL,     NULL,  true, 'manual', 'system'),
('NSE:CHENNPETRO',  'Chennai Petroleum',      'day', 2,   NULL,     NULL,  true, 'manual', 'system'),
('NSE:NFL',         'National Fertilizers',   'day', 2,   NULL,     NULL,  true, 'manual', 'system'),
('NSE:APLLTD',      'Alembic Pharma',         'day', 2,   NULL,     NULL,  true, 'manual', 'system'),
('NSE:INDIACEM',    'India Cements',          'day', 2,   NULL,     NULL,  true, 'manual', 'system'),
('NSE:LICI',        'LIC India',              'day', 2,   NULL,     NULL,  true, 'manual', 'system');

-- ============================================================
-- MULTI-ASSET: Migration for existing databases
-- ============================================================
-- Run these ALTER TABLE statements on existing databases:
--
-- ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS exchange VARCHAR(10) DEFAULT 'NSE';
-- ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS asset_class VARCHAR(15) DEFAULT 'EQUITY';
-- ALTER TABLE signals ADD COLUMN IF NOT EXISTS exchange VARCHAR(10) DEFAULT 'NSE';
-- ALTER TABLE signals ADD COLUMN IF NOT EXISTS asset_class VARCHAR(15) DEFAULT 'EQUITY';
-- ALTER TABLE active_trades ADD COLUMN IF NOT EXISTS exchange VARCHAR(10) DEFAULT 'NSE';
-- ALTER TABLE active_trades ADD COLUMN IF NOT EXISTS asset_class VARCHAR(15) DEFAULT 'EQUITY';
-- ALTER TABLE signals ADD COLUMN IF NOT EXISTS timeframe VARCHAR(10) DEFAULT '1D';
-- ALTER TABLE active_trades ADD COLUMN IF NOT EXISTS timeframe VARCHAR(10) DEFAULT '1D';
-- CREATE INDEX IF NOT EXISTS idx_watchlist_exchange ON watchlist(exchange);

-- ============================================================
-- SEED DATA: MCX Commodities
-- ============================================================
INSERT INTO watchlist (ticker, name, exchange, asset_class, timeframe, tier, active, source, added_by) VALUES
('MCX:GOLD',        'Gold',               'MCX', 'COMMODITY', 'day', 2, true, 'manual', 'system'),
('MCX:SILVER',      'Silver',             'MCX', 'COMMODITY', 'day', 2, true, 'manual', 'system'),
('MCX:CRUDEOIL',    'Crude Oil',          'MCX', 'COMMODITY', 'day', 2, true, 'manual', 'system'),
('MCX:NATURALGAS',  'Natural Gas',        'MCX', 'COMMODITY', 'day', 2, true, 'manual', 'system'),
('MCX:COPPER',      'Copper',             'MCX', 'COMMODITY', 'day', 2, true, 'manual', 'system'),
('MCX:ZINC',        'Zinc',               'MCX', 'COMMODITY', 'day', 3, true, 'manual', 'system'),
('MCX:ALUMINIUM',   'Aluminium',          'MCX', 'COMMODITY', 'day', 3, true, 'manual', 'system'),
('MCX:LEAD',        'Lead',               'MCX', 'COMMODITY', 'day', 3, true, 'manual', 'system'),
('MCX:NICKEL',      'Nickel',             'MCX', 'COMMODITY', 'day', 3, true, 'manual', 'system');

-- ============================================================
-- SEED DATA: CDS Currency Pairs
-- ============================================================
INSERT INTO watchlist (ticker, name, exchange, asset_class, timeframe, tier, active, source, added_by) VALUES
('CDS:USDINR',      'USD/INR',            'CDS', 'CURRENCY',  'day', 2, true, 'manual', 'system'),
('CDS:EURINR',      'EUR/INR',            'CDS', 'CURRENCY',  'day', 2, true, 'manual', 'system'),
('CDS:GBPINR',      'GBP/INR',            'CDS', 'CURRENCY',  'day', 3, true, 'manual', 'system'),
('CDS:JPYINR',      'JPY/INR',            'CDS', 'CURRENCY',  'day', 3, true, 'manual', 'system');

-- ============================================================
-- SEED DATA: NFO Index Futures
-- ============================================================
INSERT INTO watchlist (ticker, name, exchange, asset_class, timeframe, tier, active, source, added_by) VALUES
('NFO:NIFTY',       'Nifty 50 F&O',       'NFO', 'FNO',       '15m', 1, true, 'manual', 'system'),
('NFO:BANKNIFTY',   'Bank Nifty F&O',     'NFO', 'FNO',       '15m', 1, true, 'manual', 'system'),
('NFO:FINNIFTY',    'Fin Nifty F&O',      'NFO', 'FNO',       '15m', 2, true, 'manual', 'system'),
('NFO:MIDCPNIFTY',  'Midcap Nifty F&O',   'NFO', 'FNO',       '15m', 2, true, 'manual', 'system');
