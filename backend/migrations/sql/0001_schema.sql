-- OhBeat — физическая схема PostgreSQL (схема public)
-- Физическая ERD по этой схеме: assets/src/database_erd.drawio и assets/database_erd.png
-- Соглашения: 05_Database/Database_Schema.md
-- Роль приложения ohbeat_app и запрет UPDATE/DELETE на audit_log (NFR-32) задаются отдельно:
--   CREATE ROLE ohbeat_app NOLOGIN;
--   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ohbeat_app;
--   REVOKE UPDATE, DELETE, TRUNCATE ON public.audit_log FROM ohbeat_app;

--
--

--
-- Name: audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_log (
    id bigint NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    actor_user_id bigint,
    action character varying(64) NOT NULL,
    entity character varying(64) NOT NULL,
    entity_id bigint,
    ip character varying(64),
    details jsonb
);

--
-- Name: audit_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: audit_log_id_seq1; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.audit_log ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.audit_log_id_seq1
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: beat_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.beat_files (
    id bigint NOT NULL,
    beat_id bigint NOT NULL,
    kind character varying(32) NOT NULL,
    storage_key character varying(512) NOT NULL,
    size_bytes bigint NOT NULL,
    sha256 character(64),
    CONSTRAINT beat_files_kind_check CHECK (((kind)::text = ANY (ARRAY[('cover'::character varying)::text, ('master'::character varying)::text, ('stems'::character varying)::text, ('clean_mp3'::character varying)::text, ('preview_mp3'::character varying)::text])))
);

--
-- Name: beat_files_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.beat_files_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: beat_files_id_seq1; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.beat_files ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.beat_files_id_seq1
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: beat_genres; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.beat_genres (
    beat_id bigint NOT NULL,
    genre_id integer NOT NULL
);

--
-- Name: beat_prices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.beat_prices (
    beat_id bigint NOT NULL,
    license_id integer NOT NULL,
    price numeric(10,2) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    CONSTRAINT beat_prices_price_check CHECK (((price >= (100)::numeric) AND (price <= (500000)::numeric)))
);

--
-- Name: beats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.beats (
    id bigint NOT NULL,
    producer_id bigint NOT NULL,
    title character varying(60) NOT NULL,
    bpm smallint NOT NULL,
    musical_key character varying(16) NOT NULL,
    description text,
    duration_sec integer,
    status character varying(32) NOT NULL,
    reserved_order_id bigint,
    reserved_until timestamp with time zone,
    published_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    rejection_reason text,
    CONSTRAINT beats_bpm_check CHECK (((bpm >= 40) AND (bpm <= 300))),
    CONSTRAINT beats_check CHECK ((((status)::text = 'reserved'::text) = ((reserved_order_id IS NOT NULL) AND (reserved_until IS NOT NULL)))),
    CONSTRAINT beats_status_check CHECK (((status)::text = ANY (ARRAY[('uploading'::character varying)::text, ('processing'::character varying)::text, ('active'::character varying)::text, ('reserved'::character varying)::text, ('sold'::character varying)::text, ('rejected'::character varying)::text, ('hidden'::character varying)::text, ('deleted'::character varying)::text])))
);

--
-- Name: beats_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.beats_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: beats_id_seq1; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.beats ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.beats_id_seq1
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: billing_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.billing_profiles (
    user_id bigint NOT NULL,
    payer_type character varying(16) NOT NULL,
    last_name character varying(100) NOT NULL,
    first_name character varying(100) NOT NULL,
    middle_name character varying(100),
    email character varying(255) NOT NULL,
    phone character varying(32),
    company_name character varying(255),
    inn character varying(12),
    legal_address text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT billing_profiles_business_check CHECK ((((payer_type)::text = 'individual'::text) OR ((company_name IS NOT NULL) AND (inn IS NOT NULL) AND (legal_address IS NOT NULL)))),
    CONSTRAINT billing_profiles_inn_check CHECK (((inn IS NULL) OR ((inn)::text ~ '^([0-9]{10}|[0-9]{12})$'::text))),
    CONSTRAINT billing_profiles_payer_type_check CHECK (((payer_type)::text = ANY (ARRAY[('individual'::character varying)::text, ('business'::character varying)::text]))),
    CONSTRAINT billing_profiles_phone_check CHECK (((phone IS NULL) OR ((phone)::text ~ '^\+[1-9][0-9]{6,14}$'::text)))
);

--
-- Name: cart_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cart_items (
    user_id bigint NOT NULL,
    beat_id bigint NOT NULL,
    license_id integer NOT NULL,
    added_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: contracts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.contracts (
    id bigint NOT NULL,
    order_item_id bigint NOT NULL,
    signature_type character varying(32) NOT NULL,
    draft_sha256 character(64) NOT NULL,
    pdf_sha256 character(64),
    pdf_key character varying(512),
    signer_ip character varying(64) NOT NULL,
    signed_at timestamp with time zone NOT NULL,
    signer_phone character varying(32),
    CONSTRAINT contracts_signature_type_check CHECK (((signature_type)::text = ANY (ARRAY[('offer_accept'::character varying)::text, ('otp'::character varying)::text])))
);

--
-- Name: contracts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.contracts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: contracts_id_seq1; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.contracts ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.contracts_id_seq1
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: genres; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.genres (
    id integer NOT NULL,
    name character varying(64) NOT NULL
);

--
-- Name: genres_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.genres_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    MAXVALUE 2147483647
    CACHE 1;

--
-- Name: genres_id_seq1; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.genres ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.genres_id_seq1
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: licenses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.licenses (
    id integer NOT NULL,
    code character varying(32) NOT NULL,
    name character varying(64) NOT NULL,
    includes_mp3 boolean DEFAULT true NOT NULL,
    includes_wav boolean DEFAULT false NOT NULL,
    includes_stems boolean DEFAULT false NOT NULL,
    is_exclusive boolean DEFAULT false NOT NULL,
    CONSTRAINT licenses_code_check CHECK (((code)::text = ANY (ARRAY[('basic'::character varying)::text, ('premium'::character varying)::text, ('trackout'::character varying)::text, ('exclusive'::character varying)::text])))
);

--
-- Name: licenses_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.licenses_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    MAXVALUE 2147483647
    CACHE 1;

--
-- Name: licenses_id_seq1; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.licenses ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.licenses_id_seq1
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: order_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.order_items (
    id bigint NOT NULL,
    order_id bigint NOT NULL,
    beat_id bigint NOT NULL,
    license_id integer NOT NULL,
    producer_id bigint NOT NULL,
    price_at_purchase numeric(10,2) NOT NULL,
    platform_fee numeric(10,2) NOT NULL
);

--
-- Name: order_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.order_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: order_items_id_seq1; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.order_items ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.order_items_id_seq1
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.orders (
    id bigint NOT NULL,
    customer_id bigint NOT NULL,
    status character varying(32) NOT NULL,
    total_amount numeric(10,2) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    billing_snapshot jsonb NOT NULL,
    CONSTRAINT orders_status_check CHECK (((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('paid'::character varying)::text, ('expired'::character varying)::text, ('canceled'::character varying)::text])))
);

--
-- Name: orders_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.orders_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: orders_id_seq1; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.orders ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.orders_id_seq1
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: outbox; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outbox (
    id uuid NOT NULL,
    event_type character varying(64) NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    published_at timestamp with time zone
);

--
-- Name: payment_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payment_events (
    id bigint NOT NULL,
    provider_payment_id uuid NOT NULL,
    event character varying(64) NOT NULL,
    payload jsonb NOT NULL,
    received_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: payment_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.payment_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: payment_events_id_seq1; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.payment_events ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.payment_events_id_seq1
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: payments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payments (
    id bigint NOT NULL,
    order_id bigint NOT NULL,
    provider_payment_id uuid NOT NULL,
    idempotence_key uuid NOT NULL,
    status character varying(32) NOT NULL,
    amount numeric(10,2) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT payments_status_check CHECK (((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('waiting_for_capture'::character varying)::text, ('succeeded'::character varying)::text, ('canceled'::character varying)::text])))
);

--
-- Name: payments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.payments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: payments_id_seq1; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.payments ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.payments_id_seq1
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: producer_accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.producer_accounts (
    user_id bigint NOT NULL,
    tax_status character varying(32) NOT NULL,
    yookassa_account_id character varying(64) NOT NULL,
    pep_agreement_at timestamp with time zone NOT NULL,
    CONSTRAINT producer_accounts_tax_status_check CHECK (((tax_status)::text = ANY (ARRAY[('individual'::character varying)::text, ('self_employed'::character varying)::text, ('ip'::character varying)::text])))
);

--
-- Name: profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.profiles (
    user_id bigint NOT NULL,
    display_name character varying(100) NOT NULL,
    avatar_key character varying(255),
    bio text
);

--
-- Name: signature_otps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.signature_otps (
    id bigint NOT NULL,
    order_id bigint NOT NULL,
    code_hash character varying(255) NOT NULL,
    attempts smallint DEFAULT 0 NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    confirmed_at timestamp with time zone
);

--
-- Name: signature_otps_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.signature_otps_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: signature_otps_id_seq1; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.signature_otps ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.signature_otps_id_seq1
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: stop_words; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stop_words (
    id integer NOT NULL,
    word character varying(100) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: stop_words_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.stop_words ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.stop_words_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: user_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_roles (
    user_id bigint NOT NULL,
    role character varying(32) NOT NULL,
    CONSTRAINT user_roles_role_check CHECK (((role)::text = ANY (ARRAY[('artist'::character varying)::text, ('producer'::character varying)::text, ('admin'::character varying)::text])))
);

--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id bigint NOT NULL,
    email character varying(255) NOT NULL,
    password_hash character varying(255) NOT NULL,
    pd_consent_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: users_id_seq1; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.users ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.users_id_seq1
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);

--
-- Name: beat_files beat_files_beat_id_kind_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beat_files
    ADD CONSTRAINT beat_files_beat_id_kind_key UNIQUE (beat_id, kind);

--
-- Name: beat_files beat_files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beat_files
    ADD CONSTRAINT beat_files_pkey PRIMARY KEY (id);

--
-- Name: beat_genres beat_genres_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beat_genres
    ADD CONSTRAINT beat_genres_pkey PRIMARY KEY (beat_id, genre_id);

--
-- Name: beat_prices beat_prices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beat_prices
    ADD CONSTRAINT beat_prices_pkey PRIMARY KEY (beat_id, license_id);

--
-- Name: beats beats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beats
    ADD CONSTRAINT beats_pkey PRIMARY KEY (id);

--
-- Name: billing_profiles billing_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_profiles
    ADD CONSTRAINT billing_profiles_pkey PRIMARY KEY (user_id);

--
-- Name: cart_items cart_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cart_items
    ADD CONSTRAINT cart_items_pkey PRIMARY KEY (user_id, beat_id);

--
-- Name: contracts contracts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contracts
    ADD CONSTRAINT contracts_pkey PRIMARY KEY (id);

--
-- Name: contracts contracts_signer_phone_check; Type: CHECK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE public.contracts
    ADD CONSTRAINT contracts_signer_phone_check CHECK ((((signature_type)::text <> 'otp'::text) OR (signer_phone IS NOT NULL))) NOT VALID;

--
-- Name: genres genres_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.genres
    ADD CONSTRAINT genres_name_key UNIQUE (name);

--
-- Name: genres genres_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.genres
    ADD CONSTRAINT genres_pkey PRIMARY KEY (id);

--
-- Name: licenses licenses_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.licenses
    ADD CONSTRAINT licenses_code_key UNIQUE (code);

--
-- Name: licenses licenses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.licenses
    ADD CONSTRAINT licenses_pkey PRIMARY KEY (id);

--
-- Name: order_items order_items_order_id_beat_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_order_id_beat_id_key UNIQUE (order_id, beat_id);

--
-- Name: order_items order_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_pkey PRIMARY KEY (id);

--
-- Name: orders orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_pkey PRIMARY KEY (id);

--
-- Name: outbox outbox_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbox
    ADD CONSTRAINT outbox_pkey PRIMARY KEY (id);

--
-- Name: payment_events payment_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_events
    ADD CONSTRAINT payment_events_pkey PRIMARY KEY (id);

--
-- Name: payment_events payment_events_provider_payment_id_event_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_events
    ADD CONSTRAINT payment_events_provider_payment_id_event_key UNIQUE (provider_payment_id, event);

--
-- Name: payments payments_idempotence_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_idempotence_key_key UNIQUE (idempotence_key);

--
-- Name: payments payments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_pkey PRIMARY KEY (id);

--
-- Name: payments payments_provider_payment_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_provider_payment_id_key UNIQUE (provider_payment_id);

--
-- Name: producer_accounts producer_accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.producer_accounts
    ADD CONSTRAINT producer_accounts_pkey PRIMARY KEY (user_id);

--
-- Name: profiles profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_pkey PRIMARY KEY (user_id);

--
-- Name: signature_otps signature_otps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signature_otps
    ADD CONSTRAINT signature_otps_pkey PRIMARY KEY (id);

--
-- Name: stop_words stop_words_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stop_words
    ADD CONSTRAINT stop_words_pkey PRIMARY KEY (id);

--
-- Name: stop_words stop_words_word_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stop_words
    ADD CONSTRAINT stop_words_word_key UNIQUE (word);

--
-- Name: user_roles user_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_pkey PRIMARY KEY (user_id, role);

--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);

--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

--
-- Name: idx_beats_reserved; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_beats_reserved ON public.beats USING btree (reserved_until) WHERE ((status)::text = 'reserved'::text);

--
-- Name: audit_log audit_log_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: beat_files beat_files_beat_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beat_files
    ADD CONSTRAINT beat_files_beat_id_fkey FOREIGN KEY (beat_id) REFERENCES public.beats(id) ON DELETE CASCADE;

--
-- Name: beat_genres beat_genres_beat_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beat_genres
    ADD CONSTRAINT beat_genres_beat_id_fkey FOREIGN KEY (beat_id) REFERENCES public.beats(id) ON DELETE CASCADE;

--
-- Name: beat_genres beat_genres_genre_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beat_genres
    ADD CONSTRAINT beat_genres_genre_id_fkey FOREIGN KEY (genre_id) REFERENCES public.genres(id) ON DELETE RESTRICT;

--
-- Name: beat_prices beat_prices_beat_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beat_prices
    ADD CONSTRAINT beat_prices_beat_id_fkey FOREIGN KEY (beat_id) REFERENCES public.beats(id) ON DELETE CASCADE;

--
-- Name: beat_prices beat_prices_license_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beat_prices
    ADD CONSTRAINT beat_prices_license_id_fkey FOREIGN KEY (license_id) REFERENCES public.licenses(id) ON DELETE RESTRICT;

--
-- Name: beats beats_producer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beats
    ADD CONSTRAINT beats_producer_id_fkey FOREIGN KEY (producer_id) REFERENCES public.users(id) ON DELETE RESTRICT;

--
-- Name: billing_profiles billing_profiles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_profiles
    ADD CONSTRAINT billing_profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: cart_items cart_items_beat_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cart_items
    ADD CONSTRAINT cart_items_beat_id_fkey FOREIGN KEY (beat_id) REFERENCES public.beats(id) ON DELETE CASCADE;

--
-- Name: cart_items cart_items_license_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cart_items
    ADD CONSTRAINT cart_items_license_id_fkey FOREIGN KEY (license_id) REFERENCES public.licenses(id) ON DELETE RESTRICT;

--
-- Name: cart_items cart_items_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cart_items
    ADD CONSTRAINT cart_items_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: contracts contracts_order_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contracts
    ADD CONSTRAINT contracts_order_item_id_fkey FOREIGN KEY (order_item_id) REFERENCES public.order_items(id) ON DELETE RESTRICT;

--
-- Name: beats fk_beats_reserved_order; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beats
    ADD CONSTRAINT fk_beats_reserved_order FOREIGN KEY (reserved_order_id) REFERENCES public.orders(id) ON DELETE SET NULL;

--
-- Name: payment_events fk_payment_events_provider_payment_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_events
    ADD CONSTRAINT fk_payment_events_provider_payment_id FOREIGN KEY (provider_payment_id) REFERENCES public.payments(provider_payment_id);

--
-- Name: order_items order_items_beat_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_beat_id_fkey FOREIGN KEY (beat_id) REFERENCES public.beats(id) ON DELETE RESTRICT;

--
-- Name: order_items order_items_license_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_license_id_fkey FOREIGN KEY (license_id) REFERENCES public.licenses(id) ON DELETE RESTRICT;

--
-- Name: order_items order_items_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.orders(id) ON DELETE CASCADE;

--
-- Name: order_items order_items_producer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_producer_id_fkey FOREIGN KEY (producer_id) REFERENCES public.users(id) ON DELETE RESTRICT;

--
-- Name: orders orders_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.users(id) ON DELETE RESTRICT;

--
-- Name: payments payments_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.orders(id) ON DELETE RESTRICT;

--
-- Name: producer_accounts producer_accounts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.producer_accounts
    ADD CONSTRAINT producer_accounts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

--
-- Name: profiles profiles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: signature_otps signature_otps_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signature_otps
    ADD CONSTRAINT signature_otps_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.orders(id) ON DELETE CASCADE;

--
-- Name: user_roles user_roles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
--
