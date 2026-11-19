import { useEffect, useState } from 'react';

export interface User { uid: string; username: string; name: string; email: string; is_admin: boolean; person_id?: string | null }
export interface Session { authenticated: boolean; user: User | null; login_url?: string; google_login_url?: string; signup_url?: string; logout_url?: string }
export interface PersonAlias { id: string; alias: string; protected: boolean }
export interface Person { id: string; name: string; normalized_name: string; active: boolean; aliases: string[]; alias_details?: PersonAlias[] }
export interface Account { uid: string; username: string; name: string; email: string; is_admin: boolean; person_id: string | null; person_name?: string }
export interface Monthly { id: string; person_id: string; name: string; position: number; month: number; year: number; charge_status?: string; has_paid: boolean; amount_cents: number; charge_id: string; has_source?: boolean; source_message_id?: string | null }
export interface Entry { id: string; person_id: string; name: string; status: string; position?: number; source_section?: 'main' | 'guests'; source_position?: number; is_monthly_subscriber: boolean; invited_by?: string | null; prebuilt_team_number?: number | null; owes_single_payment: boolean; has_source?: boolean; source_message_id?: string | null; can_remove?: boolean; history_names?: string[] }
export interface SourceMessage { id: string; provider_message_id?: string | null; occurred_at: string; sender_name?: string | null; sender_id?: string | null; chat_id: string; source?: string | null; text: string; status: string; message_type?: string }
export interface Game { id: string; game_date: string; capacity: number; cutoff_at: string; starts_at: string; main_count: number; waiting_count: number; entries?: Entry[]; own_entry?: Entry | null; can_join?: boolean; can_leave?: boolean; can_add_guest?: boolean }
export interface PlayerMonthly { id: string; person_id: string; name: string; position: number }
export interface PlayerMonthlyResponse { items: PlayerMonthly[]; own_subscription: PlayerMonthly | null; can_join: boolean; can_leave: boolean }
export interface Charge { id: string; person_id: string; name: string; type: 'monthly' | 'single'; reference_date: string; amount_cents: number; status: string; paid_at?: string | null; debtor_person_id?: string; debtor_name?: string; invited_by?: string | null }
export interface AuditPerson { id?: string; name: string; is_actor?: boolean }
export interface AuditChange { kind: string; reference_date?: string; previous_name?: string; alias?: string; people?: AuditPerson[] }
export interface AuditMessageDiff { before: string | null; after: string }
export interface Audit { id: string; occurred_at: string; recorded_at?: string; actor_uid?: string; actor_name?: string; source?: string; action: string; entity_type: string; entity_id?: string; person_id?: string; before?: unknown; after?: unknown; status?: string; changes?: AuditChange[]; participant_ids?: string[]; message_diff?: AuditMessageDiff }
export interface Me { person: { id: string; name: string } | null; monthly: Monthly[]; charges: Charge[]; games: Game[]; history: Audit[]; can_manage: boolean }
export interface PlayerProfile { person_id:string; name:string; nicknames:string[]; bio:string; positions:string[]; primary_position:string|null; sex:string|null; handedness:string|null; skills:{passe:number;ataque:number;defesa:number;bloqueio:number;saque:number}|null; avatar_url:string|null; rating_average:number|null; rating_count:number; games_count:number; is_subscriber:boolean; photo_crop?:{x:number;y:number;width:number;height:number}|null }
export interface PlayerRating { stars:number|null; publish_identity:boolean }
export interface Items<T> { items: T[]; total_cents?: number }

export async function request<T>(path: string, options: RequestInit = {}, uid?: string): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (options.method && options.method !== 'GET') { headers.set('X-Fred-Request', '1'); if (uid) headers.set('X-Fred-Account', uid); }
  const response = await fetch(path, { ...options, headers, credentials: 'same-origin' });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail ?? body?.message;
    const text = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((x: { msg?: string }) => x.msg).join('; ') : null;
    throw new Error(text || (response.status === 401 ? 'Sua sessão expirou. Entre novamente.' : response.status === 403 ? 'Você não tem permissão para esta ação.' : 'Não foi possível concluir a solicitação. Tente novamente.'));
  }
  return body as T;
}
export function useResource<T>(path: string | null, revision = 0) {
  const [state, setState] = useState<{ data: T | null; error: string; loading: boolean }>({ data: null, error: '', loading: true });
  useEffect(() => {
    if (!path) { setState({ data: null, error: '', loading: false }); return; }
    const controller = new AbortController();
    setState(previous => ({ ...previous, error: '', loading: true }));
    request<T>(path, { signal: controller.signal }).then(data => { if (!controller.signal.aborted) setState({ data, error: '', loading: false }); }).catch(error => { if (!controller.signal.aborted) setState({ data: null, error: error.message, loading: false }); });
    return () => controller.abort();
  }, [path, revision]);
  return { ...state, setData: (data: T) => setState({ data, error: '', loading: false }) };
}
export const money = (cents = 0) => new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(cents / 100);
export const date = (value?: string, short = false) => value ? new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: short ? 'short' : '2-digit', year: short ? undefined : 'numeric', timeZone: 'America/Sao_Paulo' }).format(new Date(value.length === 10 ? `${value}T12:00:00-03:00` : value)) : '—';
export const dateTime = (value?: string) => value ? new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Sao_Paulo' }).format(new Date(value)) : '—';
export const monthNow = () => new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', timeZone: 'America/Sao_Paulo' }).format(new Date()).replace('/', '-');
export const query = (values: Record<string, string | undefined>) => new URLSearchParams(Object.entries(values).filter(([, value]) => value) as [string, string][]).toString();
