-- Aggregate only. No UID, goal, response, request key, or token is persisted.
CREATE TABLE ai_budget (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    month TEXT NOT NULL,
    charged_micro_usd BIGINT NOT NULL CHECK (charged_micro_usd >= 0)
);
