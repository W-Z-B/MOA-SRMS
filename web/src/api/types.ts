/** Types mirror the SRMS API serializers. Keep in step with /api/docs. */

export interface Me {
  id: number;
  username: string;
  name: string;
  roles: string[];
  is_superuser: boolean;
  mfa_required: boolean;
  mfa_verified: boolean;
  employee_no: string | null;
  student_id: number | null;
  student_no: string | null;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Campus {
  id: number;
  code: string;
  name: string;
}

export interface Notification {
  id: number;
  kind: "info" | "approval" | "alert";
  title: string;
  body: string;
  link: string;
  created_at: string;
  read_at: string | null;
}

export interface Programme {
  id: number;
  code: string;
  name: string;
  award: string;
  campus_codes: string[];
}

export interface Student {
  id: number;
  student_no: string;
  full_name: string;
  date_of_birth: string;
  gender: string;
  national_id_masked: string | null;
  email: string;
  phone: string;
  region: string;
  campus_code: string;
  programme: number;
  programme_code: string;
  programme_name: string;
  intake_year: number;
  status: string;
  is_residential: boolean;
  sponsor: string;
}

export interface Application {
  id: number;
  reference: string;
  full_name: string;
  programme: number;
  campus_code: string;
  intake_year: number;
  state: string;
  assessment_score: string | null;
  assessment_notes: string;
  decision_comment: string;
  allowed_actions: string[];
  student_no: string | null;
  waitlist_rank: number | null;
  document_count: number;
  capacity_remaining: number | null;
}

export interface ApplicationDocument {
  id: number;
  application: number;
  doc_type: "transcript" | "identification" | "medical" | "other";
  note: string;
  uploaded_by: string | null;
  created_at: string;
}

export interface Offering {
  id: number;
  code: string;
  course_code: string;
  course_title: string;
  term_code: string;
  campus_code: string;
  lecturer_employee_no: string;
  capacity: number;
  coursework_weight: string;
  exam_weight: string;
  enrolled: number;
}

export interface Enrolment {
  id: number;
  student: number;
  student_no: string;
  student_name: string;
  offering: number;
  offering_code: string;
  status: "enrolled" | "waitlisted" | "dropped" | "completed";
  waitlist_rank: number | null;
}

export interface RegistrationHold {
  id: number;
  student: number;
  student_no: string;
  reason: "missing_document" | "financial" | "academic_standing" | "other";
  reason_display: string;
  source: string;
  detail: string;
  is_active: boolean;
  resolved_at: string | null;
  created_at: string;
}

export interface Result {
  id: number;
  student_no: string;
  student_name: string;
  offering_code: string;
  coursework_mark: string | null;
  exam_mark: string | null;
  final_mark: string | null;
  letter: string;
  state: string;
  coursework_source: "manual" | "lms";
  decision_comment: string;
  allowed_actions: string[];
}

export interface TranscriptCourse {
  course_code: string;
  title: string;
  credits: string;
  final_mark: string;
  letter: string;
  points: string;
  state: string;
}

export interface Transcript {
  student_no: string;
  name: string;
  programme: string;
  campus_code: string;
  terms: { term: string; name: string; gpa: string | null; courses: TranscriptCourse[] }[];
  cumulative_gpa: string | null;
  published_only: boolean;
}

export interface ReportResult {
  key: string;
  name: string;
  rows: Record<string, string | number | null>[];
}

export interface LedgerEntry {
  kind: "charge" | "payment";
  date: string;
  description: string;
  amount: string;
  running_balance: string;
}

export interface Ledger {
  student_no: string;
  name: string;
  entries: LedgerEntry[];
  balance: string;
}

export interface Payment {
  id: number;
  student: number;
  student_no: string;
  amount: string;
  paid_on: string;
  method: "cash" | "bank_transfer" | "cheque" | "other";
  reference: string;
  note: string;
  recorded_by: string | null;
}

export const RECORDS_ROLES = ["registrar", "admissions_officer", "administrator"];
export const hasAnyRole = (me: Me, roles: string[]) => me.is_superuser || roles.some((r) => me.roles.includes(r));
