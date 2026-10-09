-- Keep the block durable even when other API instances settle earlier reservations.
ALTER TABLE ai_budget ADD COLUMN blocked BOOLEAN NOT NULL DEFAULT FALSE;
