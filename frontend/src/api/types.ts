// Shapes of API responses (REST API §2.8, §2.9).

export type Role = "artist" | "producer" | "admin";

export interface Profile {
  id: number;
  email: string;
  display_name: string;
  bio: string | null;
  avatar_url: string | null;
  roles: Role[];
}

export interface UploadForm {
  url: string;
  fields: Record<string, string>;
  key: string;
  expires_at: string;
}

export interface Billing {
  payer_type: "individual" | "business";
  last_name: string;
  first_name: string;
  middle_name: string | null;
  email: string;
  phone: string | null;
  company_name: string | null;
  inn: string | null;
  legal_address: string | null;
  updated_at: string;
}

export interface ProducerAccount {
  tax_status: "individual" | "self_employed" | "ip";
  yookassa_account_id: string;
  pep_agreement_at: string;
  roles: Role[];
}

export interface Dictionaries {
  genres: { id: number; name: string }[];
  musical_keys: string[];
  licenses: {
    code: "basic" | "premium" | "trackout" | "exclusive";
    name: string;
    includes_mp3: boolean;
    includes_wav: boolean;
    includes_stems: boolean;
    is_exclusive: boolean;
  }[];
  platform_fee_percent: string;
}

// --- Beats (REST API §2.1, §2.2, §2.4, §2.10) ---

export type BeatStatus = "uploading" | "processing" | "active" | "reserved" | "sold" | "rejected" | "hidden";
export type LicenseCode = "basic" | "premium" | "trackout" | "exclusive";
export type FileField = "wav" | "stems" | "cover";

export interface BeatLicense {
  code: LicenseCode;
  price: number;
  is_active: boolean;
}

export interface BeatCard {
  id: number;
  title: string;
  producer: { id: number; display_name: string };
  genres: string[];
  bpm: number;
  musical_key: string;
  description: string | null;
  duration_sec: number | null;
  cover_url: string | null;
  preview_url: string | null;
  is_reserved: boolean;
  licenses: BeatLicense[];
  published_at: string | null;
  // owner only
  status: BeatStatus | null;
  rejection_reason: string | null;
  created_at: string | null;
  has_stems: boolean | null;
}

export interface BeatPage {
  items: BeatCard[];
  next_cursor: string | null;
}

export interface PresignedForm {
  url: string;
  fields: Record<string, string>;
}

export interface BeatCreated {
  id: number;
  status: "uploading";
  upload_expires_at: string;
  uploads: Partial<Record<FileField, PresignedForm>>;
}

export interface UploadsReissued {
  upload_expires_at: string;
  uploads: Partial<Record<FileField, PresignedForm>>;
}

// --- Cart and orders (REST API §2.5, §2.6, §2.11) ---

// IN_YOUR_ORDER: reserved by a pending order of this Artist (GAP-66)
export type UnavailableReason = "BEAT_RESERVED" | "BEAT_SOLD" | "BEAT_NOT_AVAILABLE" | "LICENSE_INACTIVE" | "OWN_BEAT" | "IN_YOUR_ORDER";

export interface CartItem {
  beat_id: number;
  title: string;
  producer: string;
  cover_url: string | null;
  license: LicenseCode;
  price: number;
  service_fee: number;
  available: boolean;
  unavailable_reason: UnavailableReason | null;
  order_id: number | null;
}

export interface Cart {
  items: CartItem[];
  items_total: number;
  service_fee: number;
  total: number;
  fee_percent: number;
}

export interface OrderCreated {
  order_id: number;
  status: OrderStatus;
  items_total: number;
  service_fee: number;
  total: number;
  requires_signature: boolean;
  reserved_until: string | null;
}

export type OrderStatus = "pending" | "paid" | "expired" | "canceled";

export interface OrderItem {
  item_id: number;
  contract_number: string;
  beat_id: number;
  title: string;
  cover_url: string | null;
  producer: string;
  license: LicenseCode;
  price: number;
  service_fee: number;
}

export interface Order {
  order_id: number;
  status: OrderStatus;
  created_at: string;
  items_total: number;
  service_fee: number;
  total: number;
  items: OrderItem[];
  requires_signature: boolean;
  signed: boolean;
  reserved_until: string | null;
  payment_status: string | null;
}
