import { Fragment, useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowLeft, ArrowRight, CalendarDays, Check, ChevronsLeft, ChevronsRight, CircleDollarSign, Clock3, CreditCard, Eye, History, LayoutDashboard, LogOut, Menu, Pencil, RefreshCw, Search, ShieldCheck, Trash2, Trophy, Users, UsersRoundCollaboration, UserRound, Wallet, X } from 'lucide-react';
import { type Account, type Audit, type Charge, type Entry, type Game, type Items, type Me, type Monthly, type Person, type PersonAlias, type PlayerMonthlyResponse, type Session, type SourceMessage, type User, date, dateTime, money, monthNow, query, request, useResource } from './api';
import { DataCards, DataTable, type Column } from './List';
import { GamesCalendar } from './GamesCalendar';
import { Login } from './Login';
import './AliasEditor.css';
import './App.css';
import { AddButton, Avatar, Brand, Confirm, Empty, ErrorState, Field, Loading, Modal, Panel, ReadModal, Stat, Status, TextLink } from './ui';
import { ProfilePage } from './Profile';
import { PlayerProfileTrigger } from './PlayerProfileTrigger';
import MobileNavigation from './MobileNavigation';
import { useMobileViewport } from './useMobileViewport';

type Page = 'overview' | 'monthly' | 'games' | 'charges' | 'people' | 'accounts' | 'audit' | 'player' | 'player-games' | 'player-monthly' | 'player-finance';
interface Context { user: User; revision: number; busy: boolean; mutate: (path: string, method: string, body?: unknown) => Promise<boolean>; refresh: () => void; navigate: (page: Page) => void }
type HistoryPlayer = Pick<Entry, 'id' | 'person_id' | 'name'>;
type SourceHistoryMessage = Pick<SourceMessage, 'id' | 'occurred_at' | 'text' | 'status'> & Partial<Pick<SourceMessage, 'sender_name' | 'sender_id' | 'chat_id' | 'message_type' | 'source'>>;

function normalizedSourceName(value: string) {
  return value.normalize('NFD').replace(/[\u0300-\u036f\p{Cf}]/gu, '').toLocaleLowerCase('pt-BR').replace(/\s+/g, ' ').trim();
}

const sourceAnnotation = /\s*(?:\*+|[1-9]\uFE0F?\u20E3|<mensagem editada>|\(\s*(?:conv(?:\.\s*[^)]*|\s+[^)]*)?|convidad[oa](?: por\s+[^)]*)?|talvez|\d{1,2}(?::\d{2}|h\d{0,2}))\s*\)?|[-–—]\s*(?:conv\.?|convidado por)\s+.+)$/u;

function sourcePlayerLines(text: string, messageType: string | undefined, names: Set<string>) {
  const lines = text.split(/\r?\n/).map(normalizedSourceName);
  let inGuests = false;
  return lines.map((line, index) => {
    if (index === 0) return false;
    if (messageType === 'weekly_attendance' && /^(?:(?:lista (?:de )?)?(?:espera (?:dos? )?)?convidad[oa]s?|conv\.?)\s*:?$/.test(line)) {
      inGuests = true;
      return false;
    }
    const numbered = line.match(/^\d+(?:\s*[.)-]\s*|\s+)(.+)$/);
    const rawName = numbered?.[1] ?? (inGuests ? line.replace(/^[-•]\s*/, '') : '');
    let name = rawName.replace(/[✅☑✔✓]\uFE0F?/g, '').trim();
    while (name) {
      if (names.has(name)) return true;
      const withoutAnnotation = name.replace(sourceAnnotation, '').trim();
      if (name === withoutAnnotation) return false;
      name = withoutAnnotation;
    }
    return false;
  });
}

function highlightedSourceText(text: string, messageType: string | undefined, names: string[]) {
  const highlights = sourcePlayerLines(text, messageType, new Set(names.map(normalizedSourceName).filter(Boolean)));
  const lines = text.split(/\r?\n/);
  return lines.map((line, index) => <Fragment key={index}>{highlights[index] ? <mark className="source-player-highlight">{line}</mark> : line}{index < lines.length - 1 ? '\n' : ''}</Fragment>);
}

function messageIncludesPerson(message: SourceHistoryMessage, names: Set<string>) {
  return sourcePlayerLines(message.text, message.message_type, names).some(Boolean);
}

function historyPlayerNames(player: HistoryPlayer | null | undefined, people: Person[]) {
  if (!player) return undefined;
  const person = people.find(person => person.id === player.person_id);
  return [player.name, ...(person ? [person.name, ...(person.aliases ?? [])] : [])];
}

function SourceHistoryDialog({ path, personNames, title, onClose }: { path: string; personNames?: string[]; title: string; onClose: () => void }) {
  const [reload, setReload] = useState(0);
  const result = useResource<Items<SourceHistoryMessage>>(path, reload);
  const [page, setPage] = useState<number>();
  const sourceTextRef = useRef<HTMLPreElement>(null);
  const initialScrollDone = useRef(false);
  const messages = result.data?.items ?? [];
  const names = new Set(personNames?.map(normalizedSourceName).filter(Boolean));
  const appearances = names.size ? messages.flatMap((message, index) => messageIncludesPerson(message, names) ? [index] : []) : [];
  const firstAppearance = appearances[0];
  const lastAppearance = appearances.at(-1);
  const index = page ?? (personNames ? firstAppearance : messages.length - 1);
  const selected = index === undefined ? undefined : messages[index];
  useEffect(() => {
    const textArea = sourceTextRef.current;
    if (!selected || initialScrollDone.current || !textArea) return;
    initialScrollDone.current = true;
    const highlight = textArea.querySelector<HTMLElement>('.source-player-highlight');
    if (!highlight) return;
    const area = textArea.getBoundingClientRect();
    const target = highlight.getBoundingClientRect();
    if (target.top < area.top || target.bottom > area.bottom) {
      textArea.scrollTop += target.top - area.top - (textArea.clientHeight - target.height) / 2;
    }
  }, [selected?.id]);
  return <ReadModal title={title} onClose={onClose}><div className="source-history-dialog">
    {result.loading && !result.data ? <Loading/> : result.error ? <ErrorState message={result.error} retry={() => setReload(value => value + 1)}/> : !messages.length ? <Empty title="Nenhuma mensagem registrada">As próximas mensagens recebidas desta lista aparecerão aqui.</Empty> : !selected || index === undefined ? <Empty title="Aparição não encontrada">O nome do jogador não foi encontrado nas mensagens desta lista.</Empty> : <>
      <div className="source-history-meta">
        {selected.sender_name || selected.sender_id ? <strong title={selected.sender_name || selected.sender_id || undefined}>{selected.sender_name || selected.sender_id}</strong> : null}
        <Status value={selected.status}/>
        {selected.chat_id ? <span title={selected.chat_id}>{selected.chat_id}</span> : null}
        <span>{dateTime(selected.occurred_at)}</span>
      </div>
      <div className="source-history-navigation">
        <button className="icon-button" type="button" aria-label="Primeira aparição" title="Primeira aparição" disabled={firstAppearance === undefined || index === firstAppearance} onClick={() => setPage(firstAppearance)}><ChevronsLeft size={17}/></button>
        <button className="icon-button" type="button" aria-label="Mensagem anterior" title="Mensagem anterior" disabled={index <= 0} onClick={() => setPage(index - 1)}><ArrowLeft size={17}/></button>
        <span aria-live="polite">{index + 1} de {messages.length}</span>
        <button className="icon-button" type="button" aria-label="Próxima mensagem" title="Próxima mensagem" disabled={index >= messages.length - 1} onClick={() => setPage(index + 1)}><ArrowRight size={17}/></button>
        <button className="icon-button" type="button" aria-label="Última aparição" title="Última aparição" disabled={lastAppearance === undefined || index === lastAppearance} onClick={() => setPage(lastAppearance)}><ChevronsRight size={17}/></button>
      </div>
      <pre ref={sourceTextRef} className="source-history-text" tabIndex={0}>{highlightedSourceText(selected.text, selected.message_type, personNames ?? [])}</pre>
    </>}
  </div></ReadModal>;
}
const navigation: { id: Page; label: string; icon: typeof Users }[] = [{ id: 'overview', label: 'Visão geral', icon: LayoutDashboard }, { id: 'monthly', label: 'Assinantes', icon: CreditCard }, { id: 'games', label: 'Partidas', icon: CalendarDays }, { id: 'charges', label: 'Financeiro', icon: Wallet }, { id: 'people', label: 'Jogadores', icon: Users }, { id: 'accounts', label: 'Contas e acessos', icon: ShieldCheck }, { id: 'audit', label: 'Histórico de alterações', icon: History }];
const currentMonth = monthNow();
const fieldValue = (event: FormEvent<HTMLFormElement>, key: string) => String(new FormData(event.currentTarget).get(key) ?? '').trim();
const paymentOptions = [{value:'paid',label:'Pago'},{value:'pending',label:'Em aberto'},{value:'cancelled',label:'Cancelado'},{value:'waived',label:'Dispensado'}];
const listOptions = [{value:'main',label:'Principal'},{value:'waiting',label:'Espera'}];
const monthlyStatus = (m:Monthly) => m.charge_status??(m.has_paid?'paid':'pending');
const membershipOptions = [{value:'monthly',label:'Assinante'},{value:'single',label:'Convidado'}];
const principal = (entry: Entry) => ['main', 'principal'].includes(entry.status);
const fullName = (user: User) => user.name || user.username;
function UserAvatar({ user, revision }: { user:User; revision:number }) { const data=useResource<{avatar_url:string|null}>(user.person_id?'/api/me/profile':null,revision); return <Avatar name={fullName(user)} src={data.data?.avatar_url}/>; }
const hashPage = () => location.hash.slice(1).split('?')[0];
const pageFromHash = (): Page => {
  const value = hashPage();
  return (['player', 'player-games', 'player-monthly', 'player-finance'] as Page[]).includes(value as Page)
    ? value as Page
    : navigation.find(item => item.id === value)?.id ?? 'overview';
};
const hashParam = (key: string) => new URLSearchParams(location.hash.split('?')[1] ?? '').get(key);
const nextWednesday = () => { const now = new Date(); const local = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Sao_Paulo', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now); const d = new Date(`${local}T12:00:00-03:00`); d.setUTCDate(d.getUTCDate() + (3 - d.getUTCDay() + 7) % 7); return d.toISOString().slice(0, 10); };

export default function App() {
  const [revision, setRevision] = useState(0);
  const session = useResource<Session>('/api/session', revision);
  const [page, setPage] = useState<Page>(pageFromHash);
  const [hashRoute, setHashRoute] = useState(location.hash.slice(1));
  const [playerView, setPlayerView] = useState(() => hashPage().startsWith('player'));
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(null);
  const profileMenuRef = useRef<HTMLDivElement>(null);
  const profileTriggerRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { const listener = () => { const nextPage = pageFromHash(); setPage(nextPage); setHashRoute(location.hash.slice(1)); setPlayerView(nextPage.startsWith('player')); }; window.addEventListener('hashchange', listener); return () => window.removeEventListener('hashchange', listener); }, []);
  useEffect(() => {
    if (!profileMenuOpen) return;
    const closeOnOutsideClick = (event: PointerEvent) => { if (!profileMenuRef.current?.contains(event.target as Node)) setProfileMenuOpen(false); };
    document.addEventListener('pointerdown', closeOnOutsideClick);
    return () => document.removeEventListener('pointerdown', closeOnOutsideClick);
  }, [profileMenuOpen]);
  useEffect(() => { if (!notice) return; const timer = window.setTimeout(() => setNotice(null), 7000); return () => window.clearTimeout(timer); }, [notice]);
  const refresh = () => setRevision(x => x + 1);
  const navigate = (value: Page) => { location.hash = value; setPage(value); setPlayerView(value.startsWith('player')); setMenu(false); };
  const switchProfile = (profile: 'manager' | 'player') => {
    setProfileMenuOpen(false);
    if (profile === 'manager') {
      setPlayerView(false);
      location.hash = 'overview';
      setPage('overview');
    } else {
      setPlayerView(true);
      setPage('player');
      location.hash = 'player';
    }
  };
  const mutate = async (path: string, method: string, body?: unknown) => {
    if (busy) return false;
    setBusy(true);
    try { await request(path, { method, body: body === undefined ? undefined : JSON.stringify(body) }, session.data?.user?.uid); refresh(); setNotice({ text: 'Alteração salva com sucesso.', error: false }); return true; }
    catch (error) { setNotice({ text: error instanceof Error ? error.message : 'Não foi possível salvar.', error: true }); return false; }
    finally { setBusy(false); }
  };
  const publicProfileId = hashRoute.match(/^profile\/([^/?#]+)/)?.[1];
  const profileRoute = Boolean(publicProfileId || hashRoute === 'my-profile');
  const nextProfileUrl = publicProfileId ? `${location.pathname}#profile/${publicProfileId}` : '';
  if (!session.data && publicProfileId) return <><ProfilePage key={publicProfileId} id={publicProfileId} authenticated={false} onLogin={()=>{location.href=`/api/auth/login?next=${encodeURIComponent(nextProfileUrl)}`;}}/><div className="profile-public-login"><a className="button" href={`/api/auth/login?next=${encodeURIComponent(nextProfileUrl)}`}>Entrar</a></div></>;
  if (!session.data && session.loading) return <div className="initial"><Brand/><Loading/></div>;
  if (!session.data) return <div className="initial"><Brand/><ErrorState message={session.error} retry={refresh}/></div>;
  if (!session.data.authenticated || !session.data.user) {
    if (publicProfileId) return <><ProfilePage key={publicProfileId} id={publicProfileId} authenticated={false} onLogin={()=>{location.href=`${session.data?.login_url||'/api/auth/login'}?next=${encodeURIComponent(`${location.pathname}#profile/${publicProfileId}`)}`;}}/><div className="profile-public-login"><a className="button" href={`${session.data.login_url||'/api/auth/login'}?next=${encodeURIComponent(`${location.pathname}#profile/${publicProfileId}`)}`}>Entrar</a></div></>;
    return <Login session={session.data} onAuthenticated={data => data ? session.setData(data) : refresh()}/>;
  }
  const user = session.data.user;
  const isPlayerView = !user.is_admin || (playerView && Boolean(user.person_id));
  const playerPage: Page = page.startsWith('player') ? page : 'player';
  const canSwitchProfile = user.is_admin && Boolean(user.person_id);
  const ctx: Context = { user, revision, busy, mutate, refresh, navigate };
  return <div className="app-shell"><aside className={`sidebar ${menu ? 'open' : ''}`}><div className="sidebar-brand"><Brand light/><button className="icon-button mobile-close" aria-label="Fechar menu" onClick={() => setMenu(false)}><X/></button></div>{isPlayerView ? <span className="nav-caption">MEU VÔLEI</span> : null}<nav aria-label="Navegação principal">{isPlayerView ? ([['player','Meu painel',LayoutDashboard],['player-games','Partidas',CalendarDays],['player-monthly','Assinantes',CreditCard],['player-finance','Financeiro',Wallet]] as const).map(([id,label,Icon]) => <a key={id} className={`nav-item ${playerPage === id ? 'active' : ''}`} href={`#${id}`} onClick={() => { setPage(id); setMenu(false); }} aria-current={playerPage === id ? 'page' : undefined}><Icon size={19}/><span>{label}</span>{playerPage === id ? <span className="nav-dot"/> : null}</a>) : navigation.map(({ id, label, icon: Icon }) => <a key={id} className={`nav-item ${page === id ? 'active' : ''}`} href={`#${id}`} onClick={() => setMenu(false)} aria-current={page === id ? 'page' : undefined}><Icon size={19}/><span>{label}</span>{page === id ? <span className="nav-dot"/> : null}</a>)}</nav><div className="profile" ref={profileMenuRef} onKeyDown={event => { if (event.key === 'Escape' && profileMenuOpen) { setProfileMenuOpen(false); profileTriggerRef.current?.focus(); } }}><button ref={profileTriggerRef} className="profile-trigger" type="button" aria-label={`Menu do perfil de ${fullName(user)}`} aria-haspopup="menu" aria-expanded={profileMenuOpen} onClick={() => setProfileMenuOpen(value => !value)}><UserAvatar user={user} revision={revision}/></button><div><strong>{fullName(user)}</strong><small>{isPlayerView ? 'Jogador' : 'Manager'}</small></div>{profileMenuOpen ? <div className="profile-menu" role="menu" aria-label="Menu do perfil">{canSwitchProfile ? <button type="button" role="menuitem" onClick={() => switchProfile(isPlayerView ? 'manager' : 'player')}><LayoutDashboard size={16}/>{isPlayerView ? 'Painel do manager' : 'Meu painel de jogador'}</button> : null}{user.person_id?<a role="menuitem" href="#my-profile" onClick={()=>setProfileMenuOpen(false)}><UserRound size={16}/>Meu perfil</a>:null}<a role="menuitem" href={session.data.logout_url || '/api/auth/logout'}><LogOut size={16}/>Sair da conta</a></div> : null}</div></aside>{menu ? <div className="menu-overlay" onClick={() => setMenu(false)}/> : null}<div className="main-shell"><button className="mobile-menu-trigger icon-button" onClick={() => setMenu(true)} aria-label="Abrir menu"><Menu size={22}/></button><main id="main">{profileRoute ? <ProfilePage key={`${publicProfileId??'own'}-${user.person_id??''}-${user.uid}`} id={publicProfileId} own={hashRoute==='my-profile'} authenticated viewerPersonId={user.person_id} viewerUid={user.uid} onLogin={()=>{}} onSaved={()=>{refresh();}}/> : isPlayerView ? <PlayerPortal {...ctx} page={playerPage}/> : page === 'overview' ? <Overview {...ctx}/> : page === 'monthly' ? <MonthlyPage {...ctx}/> : page === 'games' ? <GamesPage {...ctx}/> : page === 'charges' ? <ChargesPage {...ctx}/> : page === 'people' ? <PeoplePage {...ctx}/> : page === 'accounts' ? <AccountsPage {...ctx}/> : <AuditPage {...ctx}/>}</main></div><MobileNavigation page={page} hashRoute={hashRoute} isPlayerView={isPlayerView} user={user} canSwitchProfile={canSwitchProfile} logoutUrl={session.data.logout_url || '/api/auth/logout'} onNavigate={navigate} onProfile={()=>{location.hash='my-profile';}} onSwitchProfile={()=>switchProfile(isPlayerView?'manager':'player')}/>{notice ? <div className={`toast ${notice.error ? 'error' : ''}`} role={notice.error ? 'alert' : 'status'}>{notice.error ? <X size={18}/> : <Check size={18}/>}<span>{notice.text}</span><button className="icon-button" onClick={() => setNotice(null)} aria-label="Fechar aviso"><X size={16}/></button></div> : null}</div>;
}

interface Debtor {person_id:string;name:string;amount_cents:number;count:number}
const debtorColumns:Column<Debtor>[]=[{id:'name',label:'Jogador',value:d=>d.name,filter:'on-click'},{id:'amount',label:'Total em aberto',kind:'money',value:d=>d.amount_cents,filter:'on-click'},{id:'count',label:'Cobranças',kind:'number',value:d=>d.count,filter:'on-click'}];
function Overview(ctx: Context) {
  const [year, month] = currentMonth.split('-');
  const monthly = useResource<Items<Monthly>>(`/api/monthly?month=${Number(month)}&year=${year}`, ctx.revision);
  const games = useResource<Items<Game>>('/api/games', ctx.revision);
  const debtors = useResource<Items<{ person_id: string; name: string; amount_cents: number; count: number }>>('/api/debtors', ctx.revision);
  const audit = useResource<Items<Audit>>('/api/audit?limit=10', ctx.revision);
  if ([monthly, games, debtors, audit].some(x => x.loading && !x.data)) return <Loading/>;
  const error = [monthly, games, debtors, audit].find(x => x.error)?.error;
  if (error) return <ErrorState message={error} retry={ctx.refresh}/>;
  const next = games.data?.items.filter(x => new Date(x.starts_at) > new Date()).sort((a, b) => a.starts_at.localeCompare(b.starts_at))[0];
  const subscribers = monthly.data?.items ?? [];
  const paid = subscribers.filter(x => monthlyStatus(x)==='paid').length;
  return <><div className="stats-grid overview-stats"><Stat label="Assinantes do mês" value={subscribers.length} note={`${paid} com pagamento em dia`} icon={<Users size={20}/>} accent/><Stat label="Total em aberto" value={money(debtors.data?.total_cents)} note={`${debtors.data?.items.length ?? 0} jogadores com pendências`} icon={<CircleDollarSign size={20}/>}/></div><div className="overview-grid"><Panel className="next-game-panel" title="Próxima partida" action={<TextLink onClick={() => ctx.navigate('games')}>Ver partidas</TextLink>}>{next ? <div className="next-game-content"><div className="game-date-block"><strong>{new Date(`${next.game_date}T12:00:00`).getDate().toString().padStart(2, '0')}</strong><span>{new Intl.DateTimeFormat('pt-BR', { month: 'long' }).format(new Date(`${next.game_date}T12:00:00`))}</span></div><div className="next-game-info"><span className="badge main">Inscrições abertas</span><h3>Vôlei de quarta</h3><p><Clock3 size={15}/>{dateTime(next.starts_at)} · horário de Brasília</p><div className="capacity-track" aria-label={`${next.main_count} confirmados e ${next.waiting_count} na espera`}><span className="capacity-main" style={{ width: `${Math.min(100, next.main_count / next.capacity * 100)}%` }}/><span className="capacity-waiting" style={{ left: `${Math.min(100, next.main_count / next.capacity * 100)}%`, width: `${Math.min(Math.max(0, 100 - next.main_count / next.capacity * 100), next.waiting_count / next.capacity * 100)}%` }}/></div><div className="capacity-label"><span><i className="capacity-key-main"/><strong>{next.main_count}</strong> confirmados</span><span><i className="capacity-key-waiting"/><strong>{next.waiting_count}</strong> na espera</span><span>{Math.max(0, next.capacity - next.main_count)} vagas</span></div></div></div> : <Empty title="A próxima partida ainda não foi criada">Adicione uma data para começar a organizar a lista.</Empty>}</Panel><Panel title="Mensalidades" action={<CreditCard size={20}/> }><div className="month-summary"><strong>{Math.round(subscribers.length ? paid / subscribers.length * 100 : 0)}<span>%</span></strong><p>das mensalidades<br/>já foram pagas</p></div><div className="payment-progress"><span style={{ width: `${subscribers.length ? paid / subscribers.length * 100 : 0}%` }}/></div><div className="summary-legend"><span><i/>{paid} pagos</span><span><i/>{subscribers.filter(x=>monthlyStatus(x)==='pending').length} em aberto</span><span>{subscribers.filter(x=>monthlyStatus(x)==='waived').length} dispensados</span></div><TextLink onClick={() => ctx.navigate('monthly')}>Conferir assinantes</TextLink></Panel></div><div className="overview-grid lower"><Panel title="Pendências" action={<TextLink onClick={() => ctx.navigate('charges')}>Ver todas</TextLink>}><DataCards name="Pendências" items={debtors.data?.items??[]} columns={debtorColumns} limit={10} showSummary={false} emptyTitle="Todo mundo em dia" emptyMessage="Nenhuma cobrança em aberto no grupo." focusFiltersOnReveal>{rows=><div className="compact-list">{rows.map(item=><div className="compact-row" key={item.person_id}><Avatar name={item.name}/><div><strong>{item.name}</strong><small>{item.count} cobrança{item.count===1?'':'s'} em aberto</small></div><strong className="amount-pending">{money(item.amount_cents)}</strong></div>)}</div>}</DataCards></Panel><Panel title="Últimas movimentações" eyebrow="ACONTECEU POR AQUI" action={<TextLink onClick={() => ctx.navigate('audit')}>Ver histórico</TextLink>}><AuditList items={audit.data?.items ?? []} compact name="Últimas movimentações" showSummary={false}/></Panel></div></>;
}

function PeopleSelect({ people, name = 'person_id', value = '', optional = false }: { people: Person[]; name?: string; value?: string; optional?: boolean }) {
  const [selected, setSelected] = useState(value);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const inputId = `player-search-${name}`;
  const selectedPerson = people.find(person => person.id === selected);
  const filtered = people.filter(person => person.name.toLocaleLowerCase('pt-BR').includes(search.toLocaleLowerCase('pt-BR')));
  return <div className="people-select">
    <input type="hidden" name={name} value={selected}/>
    <input className="people-select-validation" type="text" aria-hidden="true" tabIndex={-1} required={!optional} value={selectedPerson?.name ?? ''} onChange={() => {}} />
    <button type="button" className="people-select-trigger" aria-expanded={open} aria-controls={inputId} onClick={() => { setOpen(value => !value); setSearch(''); }}>
      <span>{selectedPerson?.name ?? (optional ? 'Sem vínculo' : 'Selecione um jogador')}</span><span aria-hidden="true">⌄</span>
    </button>
    {open ? <div className="people-select-menu"><label className="people-select-search"><Search size={16}/><input id={inputId} type="search" autoFocus value={search} onChange={event => setSearch(event.target.value)} placeholder="Pesquisar jogador" aria-label="Pesquisar jogador"/></label><div className="people-select-options" role="listbox" aria-label="Jogadores">{filtered.map(person => <button type="button" role="option" aria-selected={selected === person.id} key={person.id} onClick={() => { setSelected(person.id); setOpen(false); setSearch(''); }}>{person.name}{!person.active ? ' (inativo)' : ''}</button>)}{!filtered.length ? <span className="people-select-empty">Nenhum jogador encontrado</span> : null}</div></div> : null}
  </div>;
}
function PeoplePage(ctx: Context) {
  const result = useResource<Items<Person>>('/api/people', ctx.revision);
    const [editing, setEditing] = useState<Person | 'new' | null>(null);
  const [alias, setAlias] = useState<Person | null>(null);
  const [editingAlias, setEditingAlias] = useState<PersonAlias | null>(null);
  const [merging, setMerging] = useState<Person | null>(null);
  const submit = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const name = fieldValue(event, 'name'); const active = fieldValue(event, 'active') === 'on'; if (await ctx.mutate(editing === 'new' ? '/api/people' : `/api/people/${(editing as Person).id}`, editing === 'new' ? 'POST' : 'PATCH', editing === 'new' ? { name } : { name, active })) setEditing(null); };
  const aliasTarget = alias ? result.data?.items.find(person => person.id === alias.id) ?? alias : null;
  const aliasRows = aliasTarget?.alias_details ?? [];
  const submitAlias = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!aliasTarget) return;
    const form = event.currentTarget;
    const value = fieldValue(event, 'alias');
    const path = `/api/people/${aliasTarget.id}/aliases${editingAlias ? `/id/${editingAlias.id}` : ''}`;
    if (await ctx.mutate(path, editingAlias ? 'PATCH' : 'POST', { alias: value })) {
      setEditingAlias(null);
      if (!editingAlias) form.reset();
    }
  };
  const removeAlias = async (item: PersonAlias) => {
    if (!aliasTarget || item.protected) return;
    if (await ctx.mutate(`/api/people/${aliasTarget.id}/aliases/id/${item.id}`, 'DELETE')) {
      if (editingAlias?.id === item.id) setEditingAlias(null);
    }
  };
  return <>{result.loading && !result.data ? <Loading/> : result.error ? <ErrorState message={result.error} retry={ctx.refresh}/> : <Panel title={`${result.data?.items.length ?? 0} jogadores`} action={<AddButton onClick={() => setEditing('new')}>Adicionar jogador</AddButton>}><DataTable name="Jogadores" items={result.data?.items ?? []} rowKey={p => p.id} columns={[
{id:'name',label:'Jogador',value:p=>p.name,render:p=><div className="person-cell"><Avatar name={p.name}/><strong>{p.name}</strong></div>},
{id:'aliases',label:'Apelidos',value:p=>p.aliases.join(', '),render:p=>p.aliases.join(', ') || <span className="muted">Nenhum apelido</span>},
{id:'active',label:'Situação',kind:'select',options:[{value:'true',label:'Ativo'},{value:'false',label:'Inativo'}],value:p=>p.active,render:p=><Status value={p.active?'paid':'cancelled'}>{p.active?'Ativo':'Inativo'}</Status>}
]} actions={person=><><button className="button small secondary" onClick={()=>setMerging(person)}>Vincular entrada</button><button className="button small secondary" onClick={()=>{setEditingAlias(null);setAlias(person);}}>Editar apelidos</button><button className="icon-button" aria-label={`Editar ${person.name}`} onClick={()=>setEditing(person)}><Pencil size={16}/></button></>} emptyTitle="O time começa pelo primeiro nome" emptyMessage="Cadastre jogadores ou importe as listas pela integração."/></Panel>}{editing ? <Modal title={editing === 'new' ? 'Adicionar jogador' : 'Editar jogador'} onClose={() => setEditing(null)} onSubmit={submit} busy={ctx.busy}><Field label="Nome nas listas"><input name="name" autoFocus required maxLength={150} defaultValue={editing === 'new' ? '' : editing.name}/></Field>{editing !== 'new' ? <label className="checkbox-field"><input type="checkbox" name="active" defaultChecked={editing.active}/>Jogador ativo</label> : null}</Modal> : null}{aliasTarget ? <Modal title={`Editar apelidos de ${aliasTarget.name}`} onClose={() => {setAlias(null);setEditingAlias(null);}} busy={ctx.busy} submit={editingAlias ? 'Salvar apelido' : 'Adicionar apelido'} onSubmit={submitAlias}><p className="muted">Apelidos ajudam o Fred a reconhecer o jogador nas listas recebidas.</p>{aliasRows.length ? <ul className="alias-editor-list" aria-label="Apelidos cadastrados">{aliasRows.map(item=><li key={item.id} className="alias-editor-row"><span>{item.alias}{item.protected ? <small className="muted">Nome exibido</small> : null}</span><div className="alias-editor-actions">{item.protected ? <small className="muted">Altere o nome do jogador para trocar este apelido.</small> : <><button className="button small secondary" type="button" disabled={ctx.busy} onClick={()=>setEditingAlias(item)}>Editar</button><button className="icon-button danger" type="button" disabled={ctx.busy} aria-label={`Remover apelido ${item.alias}`} onClick={()=>removeAlias(item)}><Trash2 size={16}/></button></>}</div></li>)}</ul> : <p className="muted">Nenhum apelido cadastrado.</p>}<Field label={editingAlias ? 'Novo texto do apelido' : 'Novo apelido'} hint="O texto antigo deixará de ser reconhecido depois da edição."><input key={editingAlias?.id ?? 'new-alias'} name="alias" required autoFocus maxLength={100} defaultValue={editingAlias?.alias ?? ''}/></Field>{editingAlias ? <button type="button" className="text-link" onClick={()=>setEditingAlias(null)}>Cancelar edição</button> : null}</Modal> : null}{merging ? <Modal title={`Vincular ${merging.name} a um jogador`} onClose={() => setMerging(null)} busy={ctx.busy} submit="Vincular entrada" onSubmit={async event => { event.preventDefault(); const person_id = fieldValue(event, 'person_id'); if (person_id && await ctx.mutate(`/api/people/${merging.id}/merge`, 'POST', { target_id: person_id })) setMerging(null); }}><p>As mensalidades e participações de <strong>{merging.name}</strong> serão atribuídas ao cadastro correto.</p><Field label="Jogador correto"><PeopleSelect people={(result.data?.items ?? []).filter(person => person.id !== merging.id)}/></Field></Modal> : null}</>;
}

function MonthlyPage(ctx: Context) {
  const [period, setPeriod] = useState(() => hashParam('period') || currentMonth);
  const periods = useResource<Items<Charge>>('/api/charges?type=monthly', ctx.revision);
  const availablePeriods = [...new Set([...(periods.data?.items ?? []).map(charge => charge.reference_date.slice(0, 7)), currentMonth])].sort();
  const periodOptions = availablePeriods.length ? availablePeriods : [period];
  useEffect(() => {
    if (periods.loading) return;
    if (!availablePeriods.length || availablePeriods.includes(period)) return;
    setPeriod([...availablePeriods].reverse().find(value => value <= currentMonth) ?? availablePeriods[0]);
  }, [period, periods.data]);
  const [year, month] = period.split('-');
  const result = useResource<Items<Monthly>>(`/api/monthly?month=${Number(month)}&year=${year}`, ctx.revision);
  const requestedPersonId = hashParam('person_id');
  useEffect(() => {
    if (!result.data || !requestedPersonId) return;
    const row = document.getElementById(`monthly-entry-${requestedPersonId}`);
    if (!row) return;
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    row.classList.add('entry-targeted');
    const timer = window.setTimeout(() => row.classList.remove('entry-targeted'), 3000);
    window.history.replaceState(window.history.state, '', `#monthly?period=${period}`);
    return () => window.clearTimeout(timer);
  }, [result.data, period, requestedPersonId]);
  const people = useResource<Items<Person>>('/api/people', ctx.revision);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<Monthly | null>(null);
  const [waiving,setWaiving]=useState<{id:string;name:string}|null>(null);
  const [historyPlayer, setHistoryPlayer] = useState<HistoryPlayer | null>();
  const list = result.data?.items ?? [];
  const periodIndex = periodOptions.indexOf(period);
  const changePeriod = (amount: number) => {
    const next = periodOptions[periodIndex + amount];
    if (next) setPeriod(next);
  };
  return <><div className="stats-grid three"><Stat label="Assinantes no mês" value={list.length} note="Até 24 assinantes" icon={<Users size={20}/>} accent/><Stat label="Pagamentos confirmados" value={list.filter(x => monthlyStatus(x)==='paid').length} note={money(list.filter(x => monthlyStatus(x)==='paid').reduce((sum, x) => sum + x.amount_cents, 0)) + ' recebidos'} icon={<Check size={20}/>}/><Stat label="A receber no mês" value={money(list.filter(x => monthlyStatus(x)==='pending').reduce((sum, x) => sum + x.amount_cents, 0))} note={`${list.filter(x => monthlyStatus(x)==='pending').length} mensalidades em aberto`} icon={<Wallet size={20}/>}/></div><Panel title="Lista de assinantes" action={<div className="list-header-actions"><button className="button secondary" onClick={() => setHistoryPlayer(null)}><History size={16}/>Histórico do WhatsApp</button><AddButton onClick={() => setAdding(true)}>Adicionar assinante</AddButton></div>}><div className="toolbar"><Field label="Mês de referência"><div className="month-picker"><button type="button" className="icon-button" aria-label="Mês anterior" disabled={!periodIndex || periods.loading} onClick={() => changePeriod(-1)}><ArrowLeft size={17}/></button><select value={period} onChange={e => setPeriod(e.target.value)} aria-label="Mês de referência">{periodOptions.map(value => <option key={value} value={value}>{new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}-01T12:00:00Z`))}</option>)}</select><button type="button" className="icon-button" aria-label="Próximo mês" disabled={periodIndex < 0 || periodIndex >= periodOptions.length - 1 || periods.loading} onClick={() => changePeriod(1)}><ArrowRight size={17}/></button></div></Field></div>{periods.error ? <ErrorState message={periods.error} retry={ctx.refresh}/> : null}{result.loading && !result.data ? <Loading/> : result.error ? <ErrorState message={result.error} retry={ctx.refresh}/> : <DataTable name="Assinantes" items={list} rowKey={item=>item.id} rowId={item=>`monthly-entry-${item.person_id}`} showSummary={false} columns={[
{id:'position',label:'#',kind:'number',value:item=>item.position,render:item=><span className="position">{String(item.position).padStart(2,'0')}</span>,filter:'hidden'},
{id:'name',label:'Jogador',value:item=>item.name,render:item=><div className="person-cell"><Avatar name={item.name}/><PlayerProfileTrigger personId={item.person_id} name={item.name}/></div>,filter:'on-click'},
{id:'payment',label:'Pagamento',kind:'select',options:paymentOptions,value:item=>monthlyStatus(item),render:item=><Status value={monthlyStatus(item)}/>,filter:'on-click'}
]} actions={item=><>{item.has_source && item.source_message_id?<button className="icon-button" aria-label={`Ver mensagem de origem de ${item.name}`} title="Ver mensagem de origem" onClick={()=>setHistoryPlayer(item)}><Eye size={16}/></button>:<button className="icon-button" disabled aria-label={`Fonte indisponível para ${item.name}`} title="Fonte indisponível para esta entrada"><Eye size={16}/></button>}{['paid','pending'].includes(monthlyStatus(item))?<button className="button small secondary" disabled={ctx.busy} onClick={()=>ctx.mutate(`/api/monthly/${item.id}`,'PATCH',{has_paid:monthlyStatus(item)!=='paid'})}>{monthlyStatus(item)==='paid'?'Desfazer pagamento':'Marcar como pago'}</button>:null}{monthlyStatus(item)==='pending'&&item.charge_id?<button className="button small secondary dispense-button" disabled={ctx.busy} onClick={()=>setWaiving({id:item.charge_id,name:item.name})}>Dispensar pagamento</button>:null}{monthlyStatus(item)==='waived'?<button className="button small secondary" disabled={ctx.busy} onClick={()=>ctx.mutate(`/api/charges/${item.charge_id}`,'PATCH',{status:'pending',reason:'Cobrança reativada pelo gestor'})}>Reativar cobrança</button>:null}<button className="icon-button danger" aria-label={`Remover assinante ${item.name}`} onClick={()=>setRemoving(item)}><Trash2 size={16}/></button></>} emptyTitle="Este mês ainda está sem assinantes" emptyMessage="Adicione os jogadores que assinam o mês selecionado."/>}</Panel>{historyPlayer !== undefined ? <SourceHistoryDialog key={`monthly-${period}-${historyPlayer?.id ?? 'latest'}`} path={`/api/source-history/monthly?month=${Number(month)}&year=${year}`} personNames={historyPlayerNames(historyPlayer, people.data?.items ?? [])} title="Histórico da lista mensal" onClose={() => setHistoryPlayer(undefined)}/> : null}{adding ? <Modal title="Adicionar assinante" onClose={() => setAdding(false)} busy={ctx.busy} onSubmit={async event => { event.preventDefault(); const person_id = fieldValue(event, 'person_id'); if (await ctx.mutate('/api/monthly', 'POST', { month: Number(month), year: Number(year), person_id })) setAdding(false); }}><Field label="Jogador"><PeopleSelect people={(people.data?.items ?? []).filter(p => p.active && !list.some(item => item.person_id === p.id))}/></Field><p className="muted">Mês selecionado: {month}/{year}. Valor inicial: R$ 12,50.</p></Modal> : null}{waiving?<WaiveDialog charge={waiving} ctx={ctx} onClose={()=>setWaiving(null)}/>:null}{removing ? <Confirm title="Remover assinante?" onClose={() => setRemoving(null)} busy={ctx.busy} onConfirm={async () => { if (await ctx.mutate(`/api/monthly/${removing.id}`, 'DELETE')) setRemoving(null); }}><p>Remover <strong>{removing.name}</strong> da lista de {month}/{year}? A alteração ficará registrada no histórico.</p></Confirm> : null}</>;
}

const weeklyEntryPosition = (entry: Entry) => entry.source_position ?? entry.position;
const weeklyEntrySectionOrder = (entry: Entry) => Number(
  entry.source_section ? entry.source_section === 'guests' : !principal(entry),
);

function compareWeeklyEntries(a: Entry, b: Entry) {
  return weeklyEntrySectionOrder(a) - weeklyEntrySectionOrder(b)
    || (weeklyEntryPosition(a) ?? Number.MAX_SAFE_INTEGER) - (weeklyEntryPosition(b) ?? Number.MAX_SAFE_INTEGER);
}

function GamesPage(ctx: Context) {
  const games = useResource<Items<Game>>('/api/games', ctx.revision);
  const people = useResource<Items<Person>>('/api/people', ctx.revision);
  const [selected, setSelected] = useState('');
  const ordered = [...(games.data?.items ?? [])].sort((a, b) => b.game_date.localeCompare(a.game_date));
  const requestedDate = hashParam('date');
  const requestedPersonId = hashParam('person_id');
  const selectedId = selected || ordered.find(item => item.game_date === requestedDate)?.id || [...ordered].reverse().find(x => new Date(x.starts_at) > new Date())?.id || ordered[0]?.id;
  const detail = useResource<Game>(selectedId ? `/api/games/${selectedId}` : null, ctx.revision);
  const [create, setCreate] = useState(false);
  const [edit, setEdit] = useState(false);
  const [add, setAdd] = useState(false);
  const [entryEdit, setEntryEdit] = useState<Entry | null>(null);
  const [entrySwap, setEntrySwap] = useState<Entry | null>(null);
  const [remove, setRemove] = useState<Entry | null>(null);
  const [historyPlayer, setHistoryPlayer] = useState<HistoryPlayer | null>();
  const game = detail.data?.id === selectedId ? detail.data : undefined;
  const detailLoading = detail.loading && detail.data?.id !== selectedId;
  const entries = [...(game?.entries ?? [])].sort(compareWeeklyEntries);
  const entryOrder = new Map(entries.map((entry, index) => [entry.id, index]));
  const currentInviter = entryEdit?.invited_by ?? '';
  const inviterNames = [...new Set((people.data?.items ?? [])
    .filter(person => person.active && person.id !== entryEdit?.person_id)
    .map(person => person.name))].sort((a, b) => a.localeCompare(b, 'pt-BR'));
  if (currentInviter && !inviterNames.includes(currentInviter)) inviterNames.unshift(currentInviter);
  useEffect(() => {
    if (!game || !requestedPersonId) return;
    const row = document.getElementById(`weekly-entry-${requestedPersonId}`);
    if (!row) return;
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    row.classList.add('entry-targeted');
    const timer = window.setTimeout(() => row.classList.remove('entry-targeted'), 3000);
    window.history.replaceState(window.history.state, '', `#games?date=${game.game_date}`);
    return () => window.clearTimeout(timer);
  }, [game?.id, game?.game_date, requestedPersonId]);
  const localTime = (iso: string) => new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/Sao_Paulo', dateStyle: 'short', timeStyle: 'short' }).format(new Date(iso)).replace(' ', 'T');
  const sendGame = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const capacity = Number(fieldValue(event, 'capacity')); const starts = fieldValue(event, 'starts_at'); const game_date = create ? fieldValue(event, 'game_date') : game?.game_date; const result = await ctx.mutate(create ? '/api/games' : `/api/games/${selectedId}`, create ? 'POST' : 'PATCH', { capacity, ...(create ? { game_date } : {}), ...(starts ? { starts_at: `${starts}:00-03:00` } : {}) }); if (result) { setCreate(false); setEdit(false); } };
  return <><Panel title="" action={<div className="list-header-actions"><AddButton onClick={() => setCreate(true)}>Criar partida</AddButton>{game ? <button className="button secondary" onClick={()=>setEdit(true)}><Pencil size={16}/>Editar partida</button> : null}</div>}><div className="games-calendar-layout"><GamesCalendar games={ordered} selectedId={selectedId} onSelect={setSelected}/>{game ? <div className="games-calendar-counts"><div className="game-detail-summary"><h2>{date(game.game_date)} · {new Intl.DateTimeFormat('pt-BR', { timeZone: 'America/Sao_Paulo', hour: '2-digit', minute: '2-digit' }).format(new Date(game.starts_at))}</h2></div><div className="game-count"><strong>{entries.filter(principal).length}<span>/{game.capacity}</span></strong><small>jogadores na principal</small></div><div className="game-count secondary-count"><strong>{entries.filter(x => !principal(x)).length}</strong><small>na fila de espera</small></div></div> : null}</div>{(games.loading && !games.data) || detailLoading ? <Loading/> : games.error || detail.error ? <ErrorState message={games.error || detail.error} retry={ctx.refresh}/> : !game ? <Empty title="A bola ainda não está marcada">Crie uma data para organizar a lista e a fila de espera.</Empty> : <></>}</Panel>{game ? <Panel title="Lista da partida" action={<div className="list-header-actions games-list-actions"><button className="button secondary" onClick={() => setHistoryPlayer(null)}><History size={16}/>Histórico do WhatsApp</button><AddButton onClick={() => setAdd(true)}>Adicionar jogador</AddButton></div>}>{<DataTable name="Participantes da partida" items={entries} rowKey={entry=>entry.id} showSummary={false} defaultSort={{id:'position',direction:'asc'}} columns={[
{id:'position',label:'#',kind:'number',filterKind:'text',filterValue:e=>String(weeklyEntryPosition(e)??''),value:e=>entryOrder.get(e.id),render:e=> {
  const position = weeklyEntryPosition(e);
  return <span className="position">{position ?? '—'}</span>;
}},
{id:'name',label:'Jogador',value:e=>e.name,render:e=><div className="person-cell"><Avatar name={e.name}/><PlayerProfileTrigger personId={e.person_id} name={e.name}/></div>},
{id:'status',label:'Lista',kind:'select',options:listOptions,value:e=>principal(e)?'main':'waiting',render:e=><Status value={principal(e)?'main':'waiting'}/>},
{id:'type',label:'Tipo',kind:'select',options:membershipOptions,value:e=>e.is_monthly_subscriber?'monthly':'single',render:e=>e.is_monthly_subscriber?'Assinante':'Convidado'},
{id:'team',label:'Time',kind:'number',value:e=>e.prebuilt_team_number,render:e=>e.prebuilt_team_number?<span className="team-tag">Time {e.prebuilt_team_number}</span>:'—'},
{id:'invited',label:'Convidado por',value:e=>e.invited_by,render:e=>e.invited_by||'—'}
]} rowId={entry=>`weekly-entry-${entry.person_id}`} actions={entry=><><button className="icon-button" aria-label={`Trocar jogador de ${entry.name}`} title="Trocar jogador" onClick={()=>setEntrySwap(entry)}><UsersRoundCollaboration size={16}/></button>{entry.has_source && entry.source_message_id?<button className="icon-button" aria-label={`Ver mensagem de origem de ${entry.name}`} title="Ver mensagem de origem" onClick={()=>setHistoryPlayer(entry)}><Eye size={16}/></button>:<button className="icon-button" disabled aria-label={`Fonte indisponível para ${entry.name}`} title="Fonte indisponível para esta entrada"><Eye size={16}/></button>}<button className="icon-button" aria-label={`Editar participação de ${entry.name}`} onClick={()=>setEntryEdit(entry)}><Pencil size={16}/></button><button className="icon-button danger" aria-label={`Remover ${entry.name} da partida`} onClick={()=>setRemove(entry)}><Trash2 size={16}/></button></>} emptyTitle="Lista aberta, esperando o time" emptyMessage="Adicione jogadores ou aguarde as inscrições pelo site."/>}</Panel> : null}
{historyPlayer !== undefined && game ? <SourceHistoryDialog key={`weekly-${game.game_date}-${historyPlayer?.id ?? 'latest'}`} path={`/api/source-history/weekly?game_date=${game.game_date}`} personNames={historyPlayerNames(historyPlayer, people.data?.items ?? [])} title={`Histórico da lista de ${date(game.game_date)}`} onClose={() => setHistoryPlayer(undefined)}/> : null}
{entrySwap ? <Modal title={`Trocar jogador de ${entrySwap.name}`} onClose={() => setEntrySwap(null)} busy={ctx.busy} submit="Trocar jogador" onSubmit={async event => { event.preventDefault(); const person_id = fieldValue(event, 'person_id'); if (await ctx.mutate(`/api/games/${selectedId}/entries/${entrySwap.id}/player`, 'PATCH', { person_id })) setEntrySwap(null); }}><Field label="Selecionar jogador"><PeopleSelect people={(people.data?.items ?? []).filter(person => person.active && person.id !== entrySwap.person_id && !entries.some(entry => entry.person_id === person.id))}/></Field><p className="muted">A participação e a cobrança desta entrada serão vinculadas ao jogador selecionado.</p></Modal> : null}
{create || edit ? <Modal title={create ? 'Criar partida' : 'Editar partida'} onClose={() => { setCreate(false); setEdit(false); }} onSubmit={sendGame} busy={ctx.busy}>{create ? <Field label="Data da partida" hint="As partidas acontecem às quartas-feiras."><input name="game_date" type="date" required defaultValue={nextWednesday()}/></Field> : null}<Field label="Capacidade da lista principal"><input name="capacity" type="number" min={1} max={200} defaultValue={game && edit ? game.capacity : 24} required/></Field><Field label="Início do jogo (horário de Brasília)" hint="Jogadores podem entrar e sair até este horário."><input name="starts_at" type="datetime-local" required defaultValue={game && edit ? localTime(game.starts_at) : `${nextWednesday()}T19:30`}/></Field></Modal> : null}
{add ? <Modal title="Adicionar à partida" onClose={() => setAdd(false)} busy={ctx.busy} onSubmit={async event => { event.preventDefault(); const person_id = fieldValue(event, 'person_id'); const invited_by = fieldValue(event, 'invited_by'); if (await ctx.mutate(`/api/games/${selectedId}/entries`, 'POST', { person_id, invited_by: invited_by || null })) setAdd(false); }}><Field label="Jogador"><PeopleSelect people={(people.data?.items ?? []).filter(p => p.active && !entries.some(entry => entry.person_id === p.id))}/></Field><Field label="Convidado por (opcional)"><input name="invited_by"/></Field></Modal> : null}{entryEdit ? (
  <Modal title={`Participação de ${entryEdit.name}`} onClose={() => setEntryEdit(null)} busy={ctx.busy} onSubmit={async event => {
    event.preventDefault();
    const invited_by = fieldValue(event, 'invited_by');
    const team = fieldValue(event, 'prebuilt_team_number');
    if (await ctx.mutate(`/api/games/${selectedId}/entries/${entryEdit.id}`, 'PATCH', {
      invited_by: invited_by || null,
      prebuilt_team_number: team ? Number(team) : null,
    })) setEntryEdit(null);
  }}>
    <Field label="Time (opcional)"><input name="prebuilt_team_number" type="number" min={1} max={24} defaultValue={entryEdit.prebuilt_team_number ?? ''}/></Field>
    <Field label="Convidado por">
      <select name="invited_by" defaultValue={currentInviter}>
        <option value="">Sem convidador</option>
        {inviterNames.map(name => <option key={name} value={name}>{name}</option>)}
      </select>
    </Field>
  </Modal>
) : null}{remove ? <Confirm title="Remover da partida?" onClose={() => setRemove(null)} busy={ctx.busy} onConfirm={async () => { if (await ctx.mutate(`/api/games/${selectedId}/entries/${remove.id}`, 'DELETE')) setRemove(null); }}><p>Remover <strong>{remove.name}</strong> da lista de {date(game?.game_date)}? A fila será reorganizada e a alteração será auditada.</p></Confirm> : null}</>;
}

function WaiveDialog({charge,ctx,onClose}:{charge:{id:string;name:string};ctx:Context;onClose:()=>void}) {return <Modal title={`Dispensar pagamento de ${charge.name}`} onClose={onClose} busy={ctx.busy} submit="Dispensar pagamento" onSubmit={async event=>{event.preventDefault();const reason=fieldValue(event,'reason');if(!reason)return;if(await ctx.mutate(`/api/charges/${charge.id}`,'PATCH',{status:'waived',reason}))onClose();}}><p>A cobrança ficará dispensada. O valor não contará como recebido nem como dívida. Você poderá reativá-la depois.</p><Field label="Motivo da dispensa"><textarea name="reason" required minLength={1} maxLength={1000} rows={3} autoFocus placeholder="Explique por que este pagamento será dispensado"/></Field></Modal>;}
function chargeColumns(): Column<Charge>[] { return [
{id:'name',label:'Jogador',value:c=>c.name,render:c=><div><strong>{c.name}</strong>{c.invited_by?<small style={{display:'block',color:'var(--muted)',marginTop:3}}>Convidado por {c.invited_by}</small>:null}</div>},
{id:'reference',label:'Referência',kind:'date',value:c=>c.reference_date,render:c=>date(c.reference_date)},
{id:'type',label:'Tipo',kind:'select',options:[{value:'monthly',label:'Mensalidade'},{value:'single',label:'Convidado'}],value:c=>c.type,render:c=>c.type==='monthly'?'Mensalidade':'Convidado'},
{id:'amount',label:'Valor',kind:'money',value:c=>c.amount_cents,render:c=><span className="money">{money(c.amount_cents)}</span>},
{id:'status',label:'Situação',kind:'select',options:paymentOptions,value:c=>c.status,render:c=><Status value={c.status}/>},
{id:'paid',label:'Pagamento',kind:'datetime',value:c=>c.paid_at,render:c=>dateTime(c.paid_at??undefined)}
];}

function ChargesPage(ctx: Context) {
  const [chargePerson, setChargePerson] = useState<Debtor | null>(null);
  const [editing, setEditing] = useState<Charge | null>(null);
  const [waiving, setWaiving] = useState<{ id: string; name: string } | null>(null);
  const result = useResource<Items<Charge>>('/api/charges', ctx.revision);
  const debtors = useResource<Items<Debtor>>('/api/debtors', ctx.revision);
  const openReference = (charge: Charge) => {
    const person = `&person_id=${encodeURIComponent(charge.person_id)}`;
    location.hash = charge.type === 'monthly'
      ? 'monthly?period=' + charge.reference_date.slice(0, 7) + person
      : 'games?date=' + charge.reference_date + person;
  };
  const visibleCharges = (result.data?.items ?? []).filter(charge =>
    !chargePerson || (charge.debtor_person_id ?? charge.person_id) === chargePerson.person_id,
  );

  return <>
    <div className="stats-grid charges-stats">
      <Stat label="Total em aberto" value={money(debtors.data?.total_cents)} note="Mensalidades e cobranças de convidados" icon={<Wallet size={20}/>} accent/>
      <Stat label="Jogadores com pendências" value={debtors.data?.items.length ?? '—'} note="Todas as cobranças não pagas" icon={<Users size={20}/>}/>
    </div>

    <Panel title="Dívidas por jogador">
      {debtors.loading && !debtors.data ? <Loading/> : debtors.error ? <ErrorState message={debtors.error} retry={ctx.refresh}/> :
        <DataCards
          name="Dívidas por jogador"
          items={debtors.data?.items ?? []}
          columns={debtorColumns}
          defaultSort={{ id: 'amount', direction: 'desc' }}
          emptyTitle="Todo mundo em dia"
          emptyMessage="Nenhum jogador com cobrança em aberto."
        >
          {rows => <div className="debtor-grid">{rows.map(item =>
            <button className="debtor-card" key={item.person_id} onClick={() => setChargePerson(item)} aria-label={'Filtrar cobranças de ' + item.name}>
              <Avatar name={item.name}/>
              <div><strong>{item.name}</strong><small>{item.count} cobrança{item.count === 1 ? '' : 's'}</small></div>
              <strong className="amount-pending">{money(item.amount_cents)}</strong>
            </button>,
          )}</div>}
        </DataCards>
      }
    </Panel>

    <Panel title="Cobranças e pagamentos">
      {chargePerson ? <div className="toolbar">
        <span className="list-filter-note">Cobranças atribuídas a <strong>{chargePerson.name}</strong></span>
        <button className="text-link" onClick={() => setChargePerson(null)}>Ver todos os jogadores<X size={12}/></button>
      </div> : null}
      {result.loading && !result.data ? <Loading/> : result.error ? <ErrorState message={result.error} retry={ctx.refresh}/> :
        <DataTable
          name="Cobranças e pagamentos"
          items={visibleCharges}
          rowKey={charge => charge.id}
          columns={chargeColumns()}
          defaultFilters={{ status: { value: 'pending' } }}
          showSummary={false}
          onRowClick={openReference}
          rowLabel={charge => 'Abrir ' + (charge.type === 'monthly' ? 'mensalidade' : 'partida') + ' de ' + charge.name + ', ' + date(charge.reference_date)}
          actions={charge => <>
            {['pending', 'paid'].includes(charge.status) ? <button className="button small secondary" disabled={ctx.busy} onClick={() => ctx.mutate('/api/charges/' + charge.id, 'PATCH', { status: charge.status === 'paid' ? 'pending' : 'paid', reason: charge.status === 'paid' ? 'Pagamento desfeito pelo gestor' : 'Pagamento confirmado pelo gestor' })}>{charge.status === 'paid' ? 'Desfazer pagamento' : 'Confirmar pagamento'}</button> : null}
            {charge.status === 'pending' ? <button className="button small secondary dispense-button" disabled={ctx.busy} onClick={() => setWaiving({ id: charge.id, name: charge.name })}>Dispensar pagamento</button> : null}
            {charge.status === 'waived' ? <button className="button small secondary" disabled={ctx.busy} onClick={() => ctx.mutate('/api/charges/' + charge.id, 'PATCH', { status: 'pending', reason: 'Cobrança reativada pelo gestor' })}>Reativar cobrança</button> : null}
            <button className="icon-button" aria-label={'Editar cobrança de ' + charge.name} onClick={() => setEditing(charge)}><Pencil size={16}/></button>
          </>}
          emptyTitle="Nenhuma cobrança registrada"
          emptyMessage="As mensalidades e cobranças de convidados aparecerão aqui."
          footer={rows => <span>Total exibido: <strong>{money(rows.reduce((total, charge) => total + charge.amount_cents, 0))}</strong></span>}
        />
      }
    </Panel>

    {waiving ? <WaiveDialog charge={waiving} ctx={ctx} onClose={() => setWaiving(null)}/> : null}
    {editing ? <Modal title={'Cobrança de ' + editing.name} onClose={() => setEditing(null)} busy={ctx.busy} onSubmit={async event => {
      event.preventDefault();
      const amount = fieldValue(event, 'amount');
      const newStatus = fieldValue(event, 'status');
      const reason = fieldValue(event, 'reason');
      if (await ctx.mutate('/api/charges/' + editing.id, 'PATCH', { amount_cents: Math.round(Number(amount) * 100), status: newStatus, reason })) setEditing(null);
    }}>
      <Field label="Valor (R$)"><input type="number" name="amount" min={0} step="0.01" required defaultValue={(editing.amount_cents / 100).toFixed(2)}/></Field>
      <Field label="Situação"><select name="status" defaultValue={editing.status}><option value="pending">Em aberto</option><option value="paid">Pago</option><option value="cancelled">Cancelado</option><option value="waived" disabled={editing.status !== 'pending' && editing.status !== 'waived'}>Dispensado</option></select></Field>
      <Field label="Motivo do ajuste"><textarea name="reason" required rows={3} placeholder="Explique a alteração para o histórico"/></Field>
    </Modal> : null}
  </>;
}
function AccountsPage(ctx: Context) {
  const result = useResource<Items<Account>>('/api/accounts', ctx.revision);
  const people = useResource<Items<Person>>('/api/people', ctx.revision);
  const [editing, setEditing] = useState<Account | null>(null);
  const [removing, setRemoving] = useState<Account | null>(null);
  return <Panel title="Contas cadastradas" action={<span className="badge main"><ShieldCheck size={13}/>Acesso controlado</span>}><div className="info-strip"><ShieldCheck size={18}/>Vincule cada conta a um jogador para liberar seus dados. Acesso de gestor permite administrar todo o grupo.</div>{result.loading && !result.data ? <Loading/> : result.error ? <ErrorState message={result.error} retry={ctx.refresh}/> : <DataTable name="Contas cadastradas" items={result.data?.items??[]} rowKey={account=>account.uid} columns={[
{id:'account',label:'Conta',value:a=>a.name||a.username,render:a=><div className="person-cell"><Avatar name={a.name||a.username}/><div><strong>{a.name||a.username}</strong><small>{a.email||a.username}</small></div></div>},
{id:'email',label:'Email ou usuário',value:a=>a.email||a.username},
{id:'person',label:'Jogador vinculado',value:a=>a.person_name,render:a=>a.person_name||<span className="muted">Aguardando vínculo</span>},
{id:'linked',label:'Vínculo',kind:'select',options:[{value:'true',label:'Vinculado'},{value:'false',label:'Aguardando vínculo'}],value:a=>Boolean(a.person_id),render:a=>a.person_id?'Vinculado':'Aguardando vínculo'},
{id:'role',label:'Acesso',kind:'select',options:[{value:'true',label:'Manager'},{value:'false',label:'Jogador'}],value:a=>a.is_admin,render:a=><Status value={a.is_admin?'main':'waiting'}>{a.is_admin?'Manager':'Jogador'}</Status>}
]} actions={account=><button className="button small secondary" onClick={()=>setEditing(account)}>Gerenciar acesso</button>} emptyTitle="Nenhuma conta encontrada" emptyMessage="As contas aparecem após o primeiro acesso autenticado."/>}{editing ? <Modal title={`Acesso de ${editing.name || editing.username}`} onClose={() => setEditing(null)} busy={ctx.busy} onSubmit={async event => { event.preventDefault(); const person_id = fieldValue(event, 'person_id'); const is_admin = fieldValue(event, 'is_admin') === 'on'; if (await ctx.mutate(`/api/accounts/${encodeURIComponent(editing.uid)}`, 'PATCH', { person_id: person_id || null, is_admin })) setEditing(null); }}><Field label="Jogador vinculado" hint="A conta terá acesso apenas aos dados deste jogador, salvo se for gestora."><PeopleSelect people={people.data?.items ?? []} value={editing.person_id ?? ''} optional/></Field><label className="checkbox-field"><input type="checkbox" name="is_admin" defaultChecked={editing.is_admin}/>Conceder acesso de gestor</label><p className="muted">Gestores podem ver e alterar todas as listas, pagamentos e acessos. Esta alteração será auditada.</p><div className="info-strip"><ShieldCheck size={18}/>Excluir remove o cadastro local do Fred. O acesso no Authentik precisa ser removido separadamente; o histórico do jogador será mantido.</div><button type="button" className="button small danger" disabled={ctx.busy || editing.uid === ctx.user.uid} onClick={() => setRemoving(editing)}>Excluir conta</button></Modal> : null}{removing ? <Confirm title="Excluir conta do Fred?" onClose={() => setRemoving(null)} busy={ctx.busy} onConfirm={async () => { if (await ctx.mutate(`/api/accounts/${encodeURIComponent(removing.uid)}`, 'DELETE')) { setRemoving(null); setEditing(null); } }}><p>Excluir o cadastro local de <strong>{removing.name || removing.username}</strong> ({removing.email || removing.username})? Isso não remove o usuário do Authentik nem apaga dados do jogador ou histórico.</p></Confirm> : null}</Panel>;
}

const actionLabels: Record<string, string> = { allocation: 'Lista reorganizada', baseline: 'Dados iniciais', upsert: 'Registro atualizado', alias: 'Apelido adicionado', alias_added: 'Apelido adicionado', alias_updated: 'Apelido atualizado', remove_alias: 'Apelido removido', create: 'Cadastro criado', update: 'Dados atualizados', delete: 'Registro removido', join: 'Inscrição na partida', leave: 'Saída da partida', payment: 'Pagamento atualizado', link: 'Conta vinculada', account_updated: 'Acesso atualizado', person_created: 'Jogador cadastrado', person_updated: 'Jogador atualizado', monthly_created: 'Assinante adicionado', monthly_updated: 'Mensalidade atualizada', game_created: 'Partida criada', game_updated: 'Partida atualizada', charge_updated: 'Cobrança atualizada', entry_created: 'Inscrição adicionada', entry_deleted: 'Inscrição removida', replace_player: 'Jogador substituído', player_replaced: 'Jogador substituído', identity_transfer: 'Responsável pela cobrança atualizado', merge: 'Cadastros unificados', list_change: 'Lista atualizada' };
const sourceLabels: Record<string, string> = { system: 'Sistema', promotion: 'Promoção da fila', panel: 'Painel', admin: 'Gestor', self_service: 'Jogador', player: 'Jogador', whatsapp: 'WhatsApp', import: 'Importação', migration: 'Migração', api: 'API', manual: 'Painel' };
const entityLabels: Record<string, string> = { person: 'Jogador', account: 'Conta', game: 'Partida', weekly: 'Lista semanal', monthly: 'Mensalidade', charge: 'Cobrança' };
const auditChangeLabels: Record<string, string> = {
  subscription_added: 'adicionado à mensalidade', subscription_removed: 'removido da mensalidade',
  weekly_added: 'adicionado à lista principal', weekly_removed: 'removido da lista principal',
  guest_added: 'adicionado à lista de convidados', guest_removed: 'removido da lista de convidados',
  monthly_paid: 'mensalidade marcada como paga', guest_paid: 'pagamento de convidado registrado',
  player_replaced: 'jogador substituído', alias_added: 'apelido adicionado',
};
const auditFieldLabels: Record<string, string> = {
  name: 'Nome', alias: 'Apelido', previous_name: 'Nome anterior', status: 'Situação',
  game_date: 'Data da partida', reference_date: 'Referência', starts_at: 'Início', position: 'Posição',
  amount_cents: 'Valor', has_paid: 'Pagamento', is_admin: 'Acesso de gestor', active: 'Cadastro ativo',
  is_monthly_subscriber: 'Assinante', owes_single_payment: 'Cobrança de convidado', capacity: 'Capacidade',
  main_count: 'Confirmados', waiting_count: 'Na espera',
  invited_by: 'Convidado por', month: 'Mês', year: 'Ano', type: 'Tipo', email: 'E-mail', username: 'Usuário',
  deleted: 'Removido', detached_records: 'Vínculos ajustados', person_id: 'Jogador vinculado',
};
function auditDisplayValue(key: string, value: unknown): string {
  if (typeof value === 'boolean') {
    if (key === 'is_admin') return value ? 'Sim' : 'Não';
    if (key === 'has_paid') return value ? 'Pago' : 'Pendente';
    if (key === 'active') return value ? 'Ativo' : 'Inativo';
    return value ? 'Sim' : 'Não';
  }
  if (typeof value === 'number' && key === 'amount_cents') return money(value);
  if (typeof value === 'string') {
    if (key === 'game_date' || key === 'reference_date') return date(value);
    if (key === 'starts_at') return dateTime(value);
    const labels: Record<string, string> = { main: 'Lista principal', waiting: 'Fila de espera', paid: 'Pago', pending: 'Pendente', cancelled: 'Cancelado', waived: 'Dispensado', applied: 'Aplicado', stale: 'Evento antigo', ignored: 'Ignorado' };
    return labels[value] || value;
  }
  if (Array.isArray(value)) return value.map(item => typeof item === 'string' ? item : (item && typeof item === 'object' && 'name' in item ? String((item as { name: unknown }).name) : '')).filter(Boolean).join(', ') || `${value.length} registros`;
  if (value && typeof value === 'object') return '';
  return value == null ? '—' : String(value);
}
function auditSummaryFields(value: unknown): Map<string, string> {
  const result = new Map<string, string>();
  if (!value || typeof value !== 'object' || Array.isArray(value)) return result;
  for (const [key, item] of Object.entries(value)) {
    if (['id', 'entry_id', 'person_id', 'person_ids', 'participant_ids', 'message_id', 'previous_message_id', 'normalized_name', 'source_message_id', 'has_source'].includes(key) || item == null || typeof item === 'object' && !Array.isArray(item)) continue;
    const text = auditDisplayValue(key, item);
    if (text) result.set(key, text);
  }
  return result;
}
function auditSiteSummary(item: Audit): string[] {
  const before = auditSummaryFields(item.before);
  const after = auditSummaryFields(item.after);
  const keys = [...new Set([...before.keys(), ...after.keys()])];
  const changes = keys.flatMap(key => {
    const oldValue = before.get(key), newValue = after.get(key);
    if (oldValue === newValue || (newValue == null && key === 'deleted')) return [];
    if (oldValue == null) return [`${auditFieldLabels[key] || key.replaceAll('_', ' ')}: ${newValue}`];
    if (newValue == null) return [`${auditFieldLabels[key] || key.replaceAll('_', ' ')}: ${oldValue} removido`];
    return [`${auditFieldLabels[key] || key.replaceAll('_', ' ')}: ${oldValue} → ${newValue}`];
  });
  if (changes.length) return changes;
  return [...after].map(([key, value]) => `${auditFieldLabels[key] || key.replaceAll('_', ' ')}: ${value}`);
}
function auditChangeSummary(change: NonNullable<Audit['changes']>[number], item?: Audit): string {
  const people = change.people ?? [];
  const label = auditChangeLabels[change.kind] || change.kind.replaceAll('_', ' ');
  const reference = change.reference_date
    ? (change.kind.startsWith('subscription_') || change.kind === 'monthly_paid'
      ? new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${change.reference_date.slice(0, 7)}-01T12:00:00Z`))
      : date(change.reference_date))
    : '';
  const names = people.map(person => person.name).filter(Boolean);
  const joinedNames = names.length > 1 ? `${names.slice(0, -1).join(', ')} e ${names.at(-1)}` : names[0];
  const actor = people.find(person => person.is_actor);
  if (actor && ['weekly_added', 'guest_added', 'subscription_added'].includes(change.kind)) {
    const action = change.kind === 'subscription_added'
      ? `adicionou o próprio nome à lista de assinantes${reference ? ` de ${reference}` : ''}`
      : change.kind === 'guest_added'
        ? `adicionou o próprio nome à lista de convidados${reference ? ` em ${reference}` : ''}`
        : `adicionou o próprio nome à lista principal${reference ? ` em ${reference}` : ''}`;
    return `${actor.name} ${action}.`;
  }
  if (change.kind === 'alias_added') return `${joinedNames ? `${joinedNames}: ` : ''}${label}${change.alias ? ` “${change.alias}”` : ''}.`;
  const subject = joinedNames || change.previous_name || 'Jogador';
  const suffix = reference ? ` · ${reference}` : '';
  const eventNames: Record<string, string> = {
    subscription_added: 'Assinantes incluídos na lista de assinantes', subscription_removed: 'Assinantes removidos da lista de assinantes',
    weekly_added: 'Jogadores adicionados à lista principal', weekly_removed: 'Jogadores removidos da lista principal',
    guest_added: 'Convidados adicionados à lista de convidados', guest_removed: 'Convidados removidos da lista de convidados',
  };
  if (change.kind === 'player_replaced') {
    const previous = change.previous_name || names[0];
    const replacement = previous && names.includes(previous) ? names.filter(name => name !== previous).join(', ') : joinedNames;
    return `Jogador substituído: ${previous ? `${previous} → ` : ''}${replacement || subject}${suffix}.`;
  }
  if (change.kind === 'monthly_paid') return `${item?.actor_name || 'O gestor'} confirmou a mensalidade de ${subject}${reference ? ` referente a ${reference}` : ''}.`;
  if (change.kind === 'guest_paid') return `${item?.actor_name || 'O gestor'} confirmou o pagamento de convidado de ${subject}${reference ? ` do dia ${reference}` : ''}.`;
  if (eventNames[change.kind]) return `${eventNames[change.kind]}: ${subject}${suffix}.`;
  return `${subject} ${label}${suffix}.`;
}
function auditChangeSummaries(changes: NonNullable<Audit['changes']>, item?: Audit): string[] {
  const grouped = new Map<string, NonNullable<Audit['changes']>[number]>();
  for (const change of changes) {
    const actorGroup = change.people?.some(person => person.is_actor) ? 'actor' : 'others';
    const key = `${change.kind}|${change.reference_date ?? ''}|${change.alias ?? ''}|${change.previous_name ?? ''}|${actorGroup}`;
    const existing = grouped.get(key);
    if (!existing) grouped.set(key, { ...change, people: [...(change.people ?? [])] });
    else existing.people = [...(existing.people ?? []), ...(change.people ?? [])];
  }
  return [...grouped.values()].map(change => auditChangeSummary(change, item));
}
function auditLineDiff(before: string | null, after: string): { kind: 'added' | 'removed' | 'same'; text: string }[] {
  const oldLines = before == null ? [] : before.split(/\r?\n/);
  const newLines = after.split(/\r?\n/);
  if (before == null) return newLines.map(text => ({ kind: 'added', text }));
  const lengths = Array.from({ length: oldLines.length + 1 }, () => Array<number>(newLines.length + 1).fill(0));
  for (let i = oldLines.length - 1; i >= 0; i--) for (let j = newLines.length - 1; j >= 0; j--) {
    lengths[i][j] = oldLines[i] === newLines[j] ? lengths[i + 1][j + 1] + 1 : Math.max(lengths[i + 1][j], lengths[i][j + 1]);
  }
  const lines: { kind: 'added' | 'removed' | 'same'; text: string }[] = [];
  let i = 0, j = 0;
  while (i < oldLines.length || j < newLines.length) {
    if (i < oldLines.length && j < newLines.length && oldLines[i] === newLines[j]) lines.push({ kind: 'same', text: oldLines[i++] }), j++;
    else if (j < newLines.length && (i === oldLines.length || lengths[i][j + 1] >= lengths[i + 1][j])) lines.push({ kind: 'added', text: newLines[j++] });
    else lines.push({ kind: 'removed', text: oldLines[i++] });
  }
  return lines;
}
function auditOrigin(item: Audit) {
  const source = item.source ? sourceLabels[item.source] || item.source : 'Meu cadastro';
  const actor = item.actor_name ? (!item.actor_uid ? sourceLabels[item.actor_name] || item.actor_name : item.actor_name) : '';
  return actor && actor !== source ? `${source} · ${actor}` : source;
}
const auditColumns:Column<Audit>[]=[
{id:'date',label:'Data e hora (Brasília)',kind:'datetime',value:a=>a.occurred_at},
{id:'action',label:'Alteração',kind:'select',value:a=>actionLabels[a.action]||a.action},
{id:'origin',label:'Origem ou autor',value:a=>auditOrigin(a)},
{id:'entity',label:'Registro',kind:'select',value:a=>entityLabels[a.entity_type]||a.entity_type},
{id:'status',label:'Situação',kind:'select',options:[{value:'applied',label:'Aplicado'},{value:'stale',label:'Evento antigo'},{value:'ignored',label:'Ignorado'}],value:a=>a.status}
];
function AuditDetails({ item }: { item: Audit }) {
  if (item.message_diff) {
    const diff = auditLineDiff(item.message_diff.before, item.message_diff.after);
    return <div className="audit-change-details">
      {item.message_diff.before == null ? <p className="audit-first-message">Primeira mensagem registrada; não há uma versão anterior para comparar.</p> : null}
      <pre className="audit-line-diff" aria-label="Diferenças entre as mensagens">{diff.map((line, index) => <span className={`audit-diff-line ${line.kind}`} key={`${index}-${line.kind}`}>{line.kind === 'added' ? '+ ' : line.kind === 'removed' ? '− ' : '  '}{line.text || ' '}{'\n'}</span>)}</pre>
    </div>;
  }
  const before = auditSummaryFields(item.before);
  const after = auditSummaryFields(item.after);
  const fields = [...new Set([...before.keys(), ...after.keys()])];
  if (!fields.length) return null;
  const side = (values: Map<string, string>) => <div className="audit-field-side">{fields.map(key => <div key={key}><span>{auditFieldLabels[key] || key.replaceAll('_', ' ')}</span><p>{values.get(key) ?? '—'}</p></div>)}</div>;
  return <div className="audit-fields-diff"><section><h4>Antes</h4>{before.size ? side(before) : <p>Sem registro anterior</p>}</section><section><h4>Depois</h4>{after.size ? side(after) : <p>Sem registro posterior</p>}</section></div>;
}
function AuditList({ items, compact = false, name = "Histórico de alterações", scope, showSummary = true }: { items: Audit[]; compact?: boolean; name?: string; scope?: string; showSummary?: boolean }) { return <DataCards name={name} items={items} columns={auditColumns} scope={scope} showSummary={showSummary} showFilters={!compact} emptyTitle="Nenhuma alteração registrada" emptyMessage="As próximas movimentações aparecerão aqui.">{rows=><div className={`audit-list ${compact ? 'compact' : ''}`}>{rows.map(item => {
  const title = actionLabels[item.action] || item.action.replaceAll('_', ' ');
  const summaries = item.changes?.length ? auditChangeSummaries(item.changes, item) : auditSiteSummary(item);
  return <div className="audit-item" key={item.id}><span className="audit-icon"><History size={16}/></span><div className="audit-body"><strong>{title}</strong><p>{auditOrigin(item)}<span> · {dateTime(item.occurred_at)}</span></p>{summaries.length ? <div className="audit-summary">{summaries.map((summary, index) => <p key={`${index}-${summary}`}>{summary}</p>)}</div> : null}{!compact ? <><div className="audit-tags"><span className="badge neutral">{entityLabels[item.entity_type] || item.entity_type}</span>{item.status ? <Status value={item.status}/> : null}</div>{item.message_diff || item.before || item.after ? <details><summary>Ver alteração</summary><AuditDetails item={item}/></details> : null}</> : null}</div></div>;
})}</div>}</DataCards>; }
function AuditPage(ctx: Context) {
  const [person, setPerson] = useState('');
  const [limit, setLimit] = useState('100');
  const people = useResource<Items<Person>>('/api/people', ctx.revision);
  const result = useResource<Items<Audit>>(`/api/audit?${query({ person_id: person, limit })}`, ctx.revision);
  return <Panel title="Rastro das alterações"><div className="toolbar"><Field label="Jogador"><select value={person} onChange={e => setPerson(e.target.value)}><option value="">Todos os jogadores</option>{people.data?.items.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field><Field label="Exibir"><select value={limit} onChange={e => setLimit(e.target.value)}><option value="100">Últimos 100 eventos</option><option value="250">Últimos 250 eventos</option><option value="500">Últimos 500 eventos</option></select></Field></div><div className="info-strip"><History size={17}/>A última alteração prevalece entre o painel e o WhatsApp. Importações antigas ficam registradas sem substituir dados mais recentes.</div>{result.loading && !result.data ? <Loading/> : result.error ? <ErrorState message={result.error} retry={ctx.refresh}/> : <AuditList items={result.data?.items ?? []} scope={`até ${limit} eventos carregados`}/>}</Panel>;
}

const playerGameColumns:Column<Game>[]=[
{id:'date',label:'Data',kind:'date',value:g=>g.game_date,filter:'on-click'},
{id:'starts',label:'Início (Brasília)',kind:'datetime',value:g=>g.starts_at},
{id:'status',label:'Minha inscrição',kind:'select',options:[...listOptions,{value:'none',label:'Não inscrito'}],value:g=>g.own_entry?principal(g.own_entry)?'main':'waiting':'none',filter:'on-click'},
{id:'type',label:'Tipo',kind:'select',options:membershipOptions,value:g=>g.own_entry?g.own_entry.is_monthly_subscriber?'monthly':'single':null,filter:'on-click'},
{id:'main',label:'Confirmados',kind:'number',value:g=>g.main_count},
{id:'waiting',label:'Espera',kind:'number',value:g=>g.waiting_count},
{id:'capacity',label:'Capacidade',kind:'number',value:g=>g.capacity}
];
const playerParticipationColumns=playerGameColumns.filter(column=>['date','status','type'].includes(column.id));
function PlayerPortal(ctx: Context & { page: Page }) {
  const isMobile = useMobileViewport();
  const meResult = useResource<Me>('/api/me', ctx.revision);
  const gameList = useResource<Items<Game>>('/api/me/games', ctx.revision);
  const [selectedId, setSelectedId] = useState('');
  const selected = useResource<Game>(selectedId ? `/api/me/games/${selectedId}` : null, ctx.revision);
  const [sourceDialog, setSourceDialog] = useState<{ personNames?: string[] } | null>(null);
  const [month, setMonth] = useState(currentMonth);
  const monthly = useResource<PlayerMonthlyResponse>(`/api/me/monthly?month=${Number(month.slice(5))}&year=${month.slice(0,4)}`, ctx.revision);
  const [leaveGame, setLeaveGame] = useState(false);
  const [leaveMonth, setLeaveMonth] = useState(false);
  const [addingGuest, setAddingGuest] = useState(false);
  const [removingGuest, setRemovingGuest] = useState<Entry | null>(null);
  useEffect(() => { setLeaveGame(false); setAddingGuest(false); setRemovingGuest(null); setSourceDialog(null); }, [selectedId]);
  if (meResult.loading && !meResult.data) return <Loading/>;
  if (meResult.error) return <ErrorState message={meResult.error} retry={ctx.refresh}/>;
  if (!meResult.data?.person) return <Panel><div className="unlinked"><span className="unlinked-icon"><ShieldCheck size={32}/></span><span className="eyebrow">CONTA CRIADA, SÓ FALTA UM PASSO</span><h2>Vamos colocar seu nome no jogo.</h2><p>Um gestor precisa vincular sua conta ao seu nome nas listas. Assim que isso acontecer, suas partidas e pagamentos aparecerão aqui.</p><button className="button secondary" onClick={ctx.refresh}><RefreshCw size={17}/>Conferir meu acesso</button></div></Panel>;
  const me = meResult.data;
  const pending = me.charges.filter(charge => charge.status === 'pending');
  const finance = [...me.charges].sort((a,b) => Number(b.status === 'pending') - Number(a.status === 'pending') || b.reference_date.localeCompare(a.reference_date));
  const participations = me.games.filter(game => new Date(game.starts_at) <= new Date() && game.own_entry).sort((a,b) => b.starts_at.localeCompare(a.starts_at));
  const next = (gameList.data?.items ?? []).filter(game => new Date(game.starts_at) > new Date()).sort((a,b) => a.starts_at.localeCompare(b.starts_at))[0];
  const game = selected.data?.id === selectedId ? selected.data : gameList.data?.items.find(item => item.id === selectedId);
  const monthCurrent = month === currentMonth;
  const monthLabel = new Intl.DateTimeFormat('pt-BR',{month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(`${month}-01T12:00:00Z`));
  const moveMonth = (delta:number) => { const value = new Date(`${month}-01T12:00:00Z`); value.setUTCMonth(value.getUTCMonth()+delta); setMonth(value.toISOString().slice(0,7)); };
  if (ctx.page === 'player-games') return (
    <div className="player-page">
      <Panel title="Partidas" eyebrow="CALENDÁRIO E LISTAS">
        {gameList.loading && !gameList.data ? <Loading/> : gameList.error ? <ErrorState message={gameList.error} retry={ctx.refresh}/> : <>
          <GamesCalendar games={gameList.data?.items ?? []} selectedId={selectedId} onSelect={setSelectedId}/>
          {game ? (
            <section className="player-game-detail">
              <header className="player-game-header">
                <h2>{date(game.game_date)} · Vôlei de quarta</h2>
                <div className="player-game-controls">
                  <button className="icon-button" type="button" aria-label="Histórico da lista semanal" title="Histórico da lista semanal" disabled={!selectedId} onClick={()=>setSourceDialog({})}><History size={17}/></button>
                  {game.own_entry ? <button className="button secondary" disabled={ctx.busy || selected.loading || game.can_leave === false} onClick={()=>setLeaveGame(true)}>Sair da lista</button> : <button className="button" disabled={ctx.busy || selected.loading || game.can_join !== true} onClick={()=>ctx.mutate(`/api/me/games/${game.id}/join`,'POST')}>Entrar na lista</button>}
                  <button className="button secondary" disabled={ctx.busy || selected.loading || game.can_add_guest !== true} onClick={()=>setAddingGuest(true)}>Adicionar convidado</button>
                </div>
              </header>
              {selected.loading ? <Loading/> : selected.error ? <ErrorState message={selected.error} retry={ctx.refresh}/> : (
                <DataTable
                  name="Participantes da partida"
                  items={[...(selected.data?.entries ?? [])].sort(compareWeeklyEntries)}
                  rowKey={entry=>entry.id}
                  showSummary={false}
                  showScrollHint={!isMobile}
                  columns={[
                    {id:'position',label:'#',kind:'number',value:entry=>weeklyEntryPosition(entry),filter:'hidden',hidden:isMobile},
                    {id:'name',label:'Jogador',value:entry=>entry.name,render:entry=><PlayerProfileTrigger personId={entry.person_id} name={entry.name}/>,filter:'on-click'},
                    {id:'type',label:'Tipo',value:entry=>entry.is_monthly_subscriber?'Assinante':'Convidado',filter:'on-click',hidden:isMobile},
                  ]}
                  actions={entry=><>
                    {entry.has_source && entry.source_message_id ? <button className="icon-button" type="button" aria-label={`Ver mensagem de origem de ${entry.name}`} title="Ver mensagem de origem" onClick={()=>setSourceDialog({personNames:entry.history_names?.length ? entry.history_names : [entry.name]})}><Eye size={16}/></button> : <button className="icon-button" type="button" disabled aria-label={`Fonte indisponível para ${entry.name}`} title="Fonte indisponível para esta entrada"><Eye size={16}/></button>}
                    {entry.can_remove ? <button className="button small secondary" disabled={ctx.busy || selected.loading} onClick={()=>setRemovingGuest(entry)}>Remover</button> : null}
                  </>}
                  emptyTitle="Lista vazia"
                  emptyMessage="Ainda não há participantes nesta partida."
                />
              )}
            </section>
          ) : <Empty title="Selecione uma partida">Escolha uma data marcada no calendário para abrir a lista.</Empty>}
        </>}
      </Panel>
      {sourceDialog && game ? <SourceHistoryDialog key={`player-weekly-${game.id}-${sourceDialog.personNames?.join('|') ?? 'latest'}`} path={`/api/me/games/${game.id}/history`} personNames={sourceDialog.personNames} title={`Histórico da lista de ${date(game.game_date)}`} onClose={()=>setSourceDialog(null)}/> : null}
      {leaveGame && game ? <Confirm title="Sair da partida?" onClose={()=>setLeaveGame(false)} busy={ctx.busy} onConfirm={async()=>{if(await ctx.mutate(`/api/me/games/${game.id}/join`,'DELETE'))setLeaveGame(false);}}><p>Você vai sair da partida de <strong>{date(game.game_date)}</strong>. Se você sair antes do início da partida, a cobrança de convidado será cancelada; depois do início, ela continua sendo sua obrigação.</p></Confirm> : null}
      {addingGuest && game ? <Modal title="Adicionar convidado" onClose={()=>setAddingGuest(false)} busy={ctx.busy} submit="Adicionar convidado" onSubmit={async event=>{event.preventDefault();const name=fieldValue(event,'name');if(name&&await ctx.mutate(`/api/me/games/${game.id}/guests`,'POST',{name}))setAddingGuest(false);}}><Field label="Nome do convidado"><input name="name" required maxLength={100} autoFocus/></Field><p className="muted">A inclusão pode gerar uma cobrança de convidado para você.</p></Modal> : null}
      {removingGuest && game ? <Confirm title="Remover convidado?" onClose={()=>setRemovingGuest(null)} busy={ctx.busy} onConfirm={async()=>{if(await ctx.mutate(`/api/me/games/${game.id}/guests/${removingGuest.id}`,'DELETE'))setRemovingGuest(null);}}><p>Remover <strong>{removingGuest.name}</strong> desta partida?</p></Confirm> : null}
    </div>
  );
  if (ctx.page === 'player-monthly') return <div className="player-page"><Panel title="Assinantes" eyebrow="LISTA MENSAL" action={<div className="player-month-header-action"><div className="month-picker"><button className="icon-button" aria-label="Mês anterior" onClick={()=>moveMonth(-1)}><ArrowLeft size={17}/></button><strong aria-live="polite">{monthLabel}</strong><button className="icon-button" aria-label="Próximo mês" disabled={month>=currentMonth} onClick={()=>moveMonth(1)}><ArrowRight size={17}/></button></div>{monthly.loading ? null : monthly.data?.own_subscription ? <button className="button secondary" disabled={!monthCurrent || monthly.data.can_leave !== true || ctx.busy} onClick={()=>setLeaveMonth(true)}>Sair da lista do mês</button> : <button className="button" disabled={!monthCurrent || monthly.data?.can_join !== true || ctx.busy} onClick={()=>ctx.mutate(`/api/me/monthly?month=${Number(month.slice(5))}&year=${month.slice(0,4)}`,'POST')}>Assinar este mês</button>}</div>}>{monthly.loading ? <Loading/> : monthly.error ? <ErrorState message={monthly.error} retry={ctx.refresh}/> : <DataTable name="Assinantes do mês" items={monthly.data?.items ?? []} rowKey={item=>item.id} showSummary={false} showScrollHint={!isMobile} columns={[{id:'position',label:'#',kind:'number',value:item=>item.position,filter:'hidden'},{id:'name',label:'Jogador',value:item=>item.name,render:item=><PlayerProfileTrigger personId={item.person_id} name={item.name}/>,filter:'on-click'}]} emptyTitle="Lista mensal vazia" emptyMessage="Ainda não há assinantes neste mês."/>}</Panel>{leaveMonth ? <Confirm title="Sair da lista mensal?" onClose={()=>setLeaveMonth(false)} busy={ctx.busy} onConfirm={async()=>{if(await ctx.mutate(`/api/me/monthly?month=${Number(month.slice(5))}&year=${month.slice(0,4)}`,'DELETE'))setLeaveMonth(false);}}><p>Você sairá da lista de <strong>{monthLabel}</strong>. Cobranças mensais que já foram geradas permanecem pendentes.</p></Confirm>:null}</div>;
  if (ctx.page === 'player-finance') return <div className="player-page"><Panel title="Financeiro" eyebrow="MINHAS COBRANÇAS"><DataTable name="Minhas cobranças" items={finance} rowKey={charge=>charge.id} columns={chargeColumns()} showScrollHint={!isMobile} emptyTitle="Nenhuma cobrança por aqui" emptyMessage="Suas mensalidades e cobranças de convidados aparecerão aqui."/></Panel></div>;
  return <div className="player-page"><div className="stats-grid three"><Stat label="Meu saldo em aberto" value={money(pending.reduce((sum,x)=>sum+x.amount_cents,0))} note={`${pending.length} cobranças pendentes`} icon={<Wallet size={20}/>} accent/><Stat label="Próxima partida" value={next?date(next.game_date,true):'A definir'} note={next?.own_entry?principal(next.own_entry)?'Você está na lista principal':'Você está na espera':'Sua próxima oportunidade de jogar'} icon={<CalendarDays size={20}/>}/><Stat label="Meu histórico" value={participations.length} note="Participações registradas" icon={<Trophy size={20}/>}/></div><Panel title="Minhas participações"><DataCards name="Minhas participações" items={participations} columns={playerParticipationColumns} emptyTitle="Seu histórico começa na próxima partida" emptyMessage="Suas participações passadas ficarão salvas aqui.">{rows=><div className="compact-list">{rows.map(item=><div className="compact-row" key={item.id}><CalendarDays size={20}/><div><strong>{date(item.game_date)}</strong><small>{item.own_entry?.is_monthly_subscriber?"Assinante":"Convidado"}</small></div><Status value={item.own_entry&&principal(item.own_entry)?"main":"waiting"}/></div>)}</div>}</DataCards></Panel><div className="player-shortcuts"><a className="text-link" href="#my-profile"><UserRound size={16}/>Meu perfil</a><TextLink onClick={()=>ctx.navigate('player-games')}>Ver partidas</TextLink><TextLink onClick={()=>ctx.navigate('player-monthly')}>Ver assinantes</TextLink><TextLink onClick={()=>ctx.navigate('player-finance')}>Ver financeiro</TextLink></div></div>;
}
