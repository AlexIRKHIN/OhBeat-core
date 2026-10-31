-- Additions to schema.sql (ADR 0007). The 21 tables of the reference schema are not changed.

-- ASSUMPTION: GAP-1 — storage for refresh token rotation and logout.
-- A family is the chain of tokens issued from one login; reuse of a revoked token revokes the family.
CREATE TABLE public.refresh_tokens (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    family_id uuid NOT NULL,
    token_hash character(64) NOT NULL UNIQUE,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    replaced_by_id bigint REFERENCES public.refresh_tokens(id)
);
CREATE INDEX idx_refresh_tokens_family ON public.refresh_tokens (family_id);
CREATE INDEX idx_refresh_tokens_user ON public.refresh_tokens (user_id);

-- ASSUMPTION: GAP-1 — login attempts for the limit "5 failures in 15 minutes" (REST API §2.8).
CREATE TABLE public.login_attempts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email character varying(255) NOT NULL,
    attempted_at timestamp with time zone DEFAULT now() NOT NULL,
    succeeded boolean NOT NULL,
    ip character varying(64)
);
CREATE INDEX idx_login_attempts_email_time ON public.login_attempts (email, attempted_at);

-- ASSUMPTION: GAP-2 — one contract per order item, as in the logical model.
ALTER TABLE public.contracts ADD CONSTRAINT contracts_order_item_id_key UNIQUE (order_item_id);

-- ASSUMPTION: GAP-3 — indexes for the catalog, foreign keys and Audit Log filters.
CREATE INDEX idx_beats_catalog ON public.beats (published_at DESC, id DESC)
    WHERE status IN ('active', 'reserved');
CREATE INDEX idx_beats_producer ON public.beats (producer_id);
CREATE INDEX idx_beat_genres_genre ON public.beat_genres (genre_id);
CREATE INDEX idx_order_items_producer ON public.order_items (producer_id);
CREATE INDEX idx_orders_customer ON public.orders (customer_id, created_at DESC);
CREATE INDEX idx_payments_order ON public.payments (order_id);
CREATE INDEX idx_signature_otps_order ON public.signature_otps (order_id);
CREATE INDEX idx_outbox_unpublished ON public.outbox (created_at) WHERE published_at IS NULL;
CREATE INDEX idx_audit_log_occurred ON public.audit_log (occurred_at DESC);
CREATE INDEX idx_audit_log_action ON public.audit_log (action, occurred_at DESC);
CREATE INDEX idx_audit_log_entity ON public.audit_log (entity, entity_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON public.refresh_tokens, public.login_attempts TO ohbeat_app;

-- ASSUMPTION: GAP-5 — "GRANT ... ON ALL TABLES" in 0001 also covered Alembic's service table;
-- the application has no business there.
REVOKE ALL ON public.alembic_version FROM ohbeat_app;
