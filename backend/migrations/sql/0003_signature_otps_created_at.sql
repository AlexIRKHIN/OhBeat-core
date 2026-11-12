-- Additions to schema.sql for slice 4 (ADR 0007, decision of the analyst 12.11.2026).

-- ASSUMPTION: GAP-70 — NFR-31 limits "a new code not earlier than in 60 s" and "at most 5 codes per hour
-- per user" need the moment a code was sent. Existing rows (none before slice 4) get the time of migration.
ALTER TABLE public.signature_otps ADD COLUMN created_at timestamp with time zone DEFAULT now() NOT NULL;

-- The latest code of an order, and the codes of one user in the last hour (joined through orders.customer_id)
CREATE INDEX idx_signature_otps_order_created ON public.signature_otps (order_id, created_at);
CREATE INDEX idx_signature_otps_created ON public.signature_otps (created_at);
