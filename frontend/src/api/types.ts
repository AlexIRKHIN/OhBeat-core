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
