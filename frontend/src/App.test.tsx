import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import App from './App';

vi.mock('./components/GlassSurface', () => ({
  default: ({ children, className }: { children: ReactNode; className?: string }) => <div className={className}>{children}</div>,
}));

describe('troca de perfil', () => {
  const renderAs = async (user: { uid: string; username: string; name: string; is_admin: boolean; person_id?: string | null }, hasPerson = false) => {
    window.history.replaceState({}, '', '/#overview');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const body = path === '/api/session'
        ? { authenticated: true, user }
        : path === '/api/me'
          ? { person: hasPerson ? { id: 'player-1', name: user.name } : null, monthly: [], charges: [], games: [], history: [], can_manage: user.is_admin }
          : { items: [] };
      return { ok: true, json: async () => body };
    }));
    render(<App/>);
    await screen.findByRole('button', { name: `Menu do perfil de ${user.name}` });
  };

  it('manager vinculado alterna para o painel de jogador e volta ao manager', async () => {
    await renderAs({ uid: 'manager', username: 'gestor', name: 'Gestor', is_admin: true, person_id: 'player-1' }, true);
    fireEvent.click(screen.getByRole('button', { name: 'Menu do perfil de Gestor' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Meu painel de jogador' }));
    await screen.findByRole('heading', { name: 'Minhas participações' });
    fireEvent.click(screen.getByRole('button', { name: 'Menu do perfil de Gestor' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Painel do manager' }));
    await screen.findByRole('heading', { name: 'Próxima partida' });
  });

  it('perfil manager sem pessoa vinculada não oferece troca', async () => {
    await renderAs({ uid: 'manager', username: 'gestor', name: 'Gestor', is_admin: true }, false);
    fireEvent.click(screen.getByRole('button', { name: 'Menu do perfil de Gestor' }));
    expect(screen.queryByRole('menuitem', { name: 'Meu painel de jogador' })).toBeNull();
  });

  it('perfil somente jogador não oferece troca para manager', async () => {
    await renderAs({ uid: 'player', username: 'jogador', name: 'Jogador', is_admin: false, person_id: 'player-1' });
    fireEvent.click(screen.getByRole('button', { name: 'Menu do perfil de Jogador' }));
    expect(screen.queryByRole('menuitem', { name: 'Painel do manager' })).toBeNull();
  });
});

describe('painel mensal', () => {
  const paths: string[] = [];
  const requests: { path: string; init?: RequestInit }[] = [];

  beforeEach(() => {
    paths.length = 0;
    requests.length = 0;
    window.history.replaceState({}, '', '/#monthly');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      paths.push(path);
      requests.push({ path, init });
      const body = path === '/api/session'
        ? { authenticated: true, user: { uid: 'admin', username: 'gestor', name: 'Gestor', is_admin: true } }
        : path === '/api/charges?type=monthly'
          ? { items: [
            { id: 'december', person_id: 'p', name: 'Jogador', type: 'monthly', reference_date: '2025-12-01', amount_cents: 1250, status: 'paid' },
            { id: 'january', person_id: 'p', name: 'Jogador', type: 'monthly', reference_date: '2026-01-01', amount_cents: 1250, status: 'paid' },
          ] }
          : path === '/api/games'
            ? { items: [{ id: 'game', game_date: '2026-12-02', starts_at: '2026-12-02T19:30:00-03:00', cutoff_at: '2026-12-02T16:00:00-03:00', capacity: 24, main_count: 2, waiting_count: 1 }] }
            : path === '/api/games/game'
              ? { id: 'game', game_date: '2026-12-02', starts_at: '2026-12-02T19:30:00-03:00', cutoff_at: '2026-12-02T16:00:00-03:00', capacity: 24, main_count: 2, waiting_count: 1, entries: [
                { id: 'wait', person_id: 'wait', name: 'Espera', status: 'waiting', position: 1, is_monthly_subscriber: false, owes_single_payment: false },
                { id: 'main-2', person_id: 'main-2', name: 'Principal dois', status: 'main', position: 2, is_monthly_subscriber: false, owes_single_payment: false, invited_by: 'Apelido da lista antiga' },
                { id: 'main-1', person_id: 'main-1', name: 'Principal um', status: 'main', position: 1, is_monthly_subscriber: false, owes_single_payment: false },
              ] }
          : path === '/api/people'
            ? { items: [
              { id: 'source', name: 'Gomes 👆🏾', normalized_name: 'gomes', active: true, aliases: ['Gomão'], alias_details: [{ id: 'gomao', alias: 'Gomão', protected: false }] },
              { id: 'target', name: 'Gomes', normalized_name: 'gomes', active: true, aliases: [], alias_details: [] },
            ] }
          : { items: [] };
      return { ok: true, json: async () => body };
    }));
  });

  it('simplifica o overview e revela os filtros de pendências com foco', async () => {
    window.history.replaceState({}, '', '/#overview');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const body = path === '/api/session'
        ? { authenticated: true, user: { uid: 'admin', username: 'gestor', name: 'Gestor', is_admin: true } }
        : path === '/api/games'
          ? { items: [{ id: 'game', game_date: '2026-12-02', starts_at: '2026-12-02T19:30:00-03:00', cutoff_at: '2026-12-02T16:00:00-03:00', capacity: 24, main_count: 2, waiting_count: 3 }] }
          : path === '/api/debtors'
            ? { items: Array.from({ length: 12 }, (_, index) => ({ person_id: `p-${index}`, name: `Jogador ${index + 1}`, amount_cents: 1200, count: 2 })), total_cents: 14400 }
            : { items: [] };
      return { ok: true, json: async () => body };
    }));
    render(<App/>);

    await screen.findByRole('heading', { name: 'Próxima partida' });
    expect(screen.queryByText('Mensalidades recebidas')).toBeNull();
    expect(screen.queryByText('Próxima partida', { selector: '.stat-top' })).toBeNull();
    expect(document.querySelector('.capacity-waiting')).toBeTruthy();
    expect(document.querySelector('.capacity-label')?.textContent).toContain('3 na espera');
    expect(screen.queryByText('Gerenciar lista')).toBeNull();
    expect(screen.queryByText('PRÓXIMO ENCONTRO')).toBeNull();
    expect(screen.getByRole('heading', { name: 'Mensalidades' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Pendências' })).toBeTruthy();
    expect(screen.queryByText('MENSALIDADES')).toBeNull();
    expect(screen.queryByText('FINANCEIRO')).toBeNull();

    const filters = screen.getByRole('group', { name: 'Filtros e ordenação — Pendências' });
    expect(within(filters).queryByRole('searchbox', { name: 'Filtrar Jogador — Pendências' })).toBeNull();
    fireEvent.click(within(filters).getByRole('button', { name: 'Jogador' }));
    const playerFilter = within(filters).getByRole('searchbox', { name: 'Filtrar Jogador — Pendências' });
    expect(document.activeElement).toBe(playerFilter);
    expect(document.querySelectorAll('.compact-row')).toHaveLength(10);
    expect(within(screen.getByRole('heading', { name: 'Pendências' }).closest('section')!).queryByRole('status')).toBeNull();
    expect(screen.queryByRole('group', { name: 'Filtros e ordenação — Últimas movimentações' })).toBeNull();
    expect(screen.queryByText(/últimos 5 eventos carregados/)).toBeNull();
  });

  it('avança e volta um mês, incluindo a virada do ano', async () => {
    render(<App/>);
    const month = await screen.findByRole('combobox', { name: 'Mês de referência' }) as HTMLSelectElement;
    await waitFor(() => expect([...month.options].some(option => option.value === '2026-01')).toBe(true));
    expect([...month.options].some(option => option.value.startsWith('2022-'))).toBe(false);
    fireEvent.change(month, { target: { value: '2026-01' } });
    fireEvent.click(screen.getByRole('button', { name: 'Mês anterior' }));
    expect(month.value).toBe('2025-12');
    await waitFor(() => expect(paths).toContain('/api/monthly?month=12&year=2025'));
    fireEvent.click(screen.getByRole('button', { name: 'Próximo mês' }));
    expect(month.value).toBe('2026-01');
    await waitFor(() => expect(paths).toContain('/api/monthly?month=1&year=2026'));
  });

  it('remove os textos de apresentação marcados para exclusão', async () => {
    render(<App/>);
    await screen.findByRole('heading', { name: 'Lista de assinantes' });
    expect(screen.queryByText('MENOS PLANILHA. MAIS VÔLEI.')).toBeNull();
    expect(screen.queryByText('Mensalista tem prioridade até quarta, às 16h.')).toBeNull();
    expect(screen.queryByText('Seu vôlei, organizado.')).toBeNull();
    expect(screen.queryByText('Conectado')).toBeNull();
    expect(screen.queryByText('Vôlei de quarta')).toBeNull();
    expect(screen.queryByText(/A organização fica aqui/)).toBeNull();
    expect(document.querySelector('.today, .topbar, .page-footer')).toBeNull();
    expect(screen.getByRole('button', { name: 'Abrir menu' })).toBeTruthy();
  });

  it('atribui as entradas de um cadastro duplicado ao jogador escolhido', async () => {
    window.history.replaceState({}, '', '/#people');
    render(<App/>);
    const duplicate = await screen.findByText('Gomes 👆🏾');
    fireEvent.click(within(duplicate.closest('tr')!).getByRole('button', { name: 'Vincular entrada' }));
    const dialog = within(screen.getByRole('dialog', { name: 'Vincular Gomes 👆🏾 a um jogador' }));
    fireEvent.click(dialog.getByRole('button', { name: 'Selecione um jogador' }));
    fireEvent.change(dialog.getByRole('searchbox', { name: 'Pesquisar jogador' }), { target: { value: 'Gomes' } });
    fireEvent.click(dialog.getByRole('option', { name: 'Gomes' }));
    fireEvent.click(dialog.getByRole('button', { name: 'Vincular entrada' }));
    await waitFor(() => expect(requests.some(request => request.path === '/api/people/source/merge')).toBe(true));
    const merge = requests.find(request => request.path === '/api/people/source/merge');
    expect(merge?.init?.method).toBe('POST');
    expect(JSON.parse(String(merge?.init?.body))).toEqual({ target_id: 'target' });
  });

  it('edita, remove e adiciona apelidos pela lista do jogador', async () => {
    window.history.replaceState({}, '', '/#people');
    render(<App/>);
    const duplicate = await screen.findByText('Gomes 👆🏾');
    fireEvent.click(within(duplicate.closest('tr')!).getByRole('button', { name: 'Editar apelidos' }));
    const dialog = screen.getByRole('dialog', { name: 'Editar apelidos de Gomes 👆🏾' });
    expect(within(dialog).getByText('Gomão')).toBeTruthy();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Editar' }));
    expect(within(dialog).getByText('Novo texto do apelido')).toBeTruthy();
    fireEvent.change(dialog.querySelector<HTMLInputElement>('input[name="alias"]')!, { target: { value: 'Gomes Junior' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Salvar apelido' }));
    await waitFor(() => expect(requests.some(request => request.path === '/api/people/source/aliases/id/gomao' && request.init?.method === 'PATCH')).toBe(true));
    const edit = requests.find(request => request.path === '/api/people/source/aliases/id/gomao' && request.init?.method === 'PATCH');
    expect(JSON.parse(String(edit?.init?.body))).toEqual({ alias: 'Gomes Junior' });

    fireEvent.click(within(dialog).getByRole('button', { name: 'Remover apelido Gomão' }));
    await waitFor(() => expect(requests.some(request => request.path === '/api/people/source/aliases/id/gomao' && request.init?.method === 'DELETE')).toBe(true));

    fireEvent.change(dialog.querySelector<HTMLInputElement>('input[name="alias"]')!, { target: { value: 'Gomes Júnior' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Adicionar apelido' }));
    await waitFor(() => expect(requests.some(request => request.path === '/api/people/source/aliases' && request.init?.method === 'POST')).toBe(true));
    const added = requests.find(request => request.path === '/api/people/source/aliases' && request.init?.method === 'POST');
    expect(JSON.parse(String(added?.init?.body))).toEqual({ alias: 'Gomes Júnior' });
  });

  it('abre partidas pelo calendário e ordena a lista na ordem oficial por posição', async () => {
    window.history.replaceState({}, '', '/#games');
    render(<App/>);
    const table = await screen.findByRole('table', { name: 'Participantes da partida' });
    const rows = [...table.querySelectorAll('tbody tr')].map(row => row.querySelector('[data-label="Jogador"]')?.textContent);
    expect(rows).toEqual(['PUPrincipal um', 'PDPrincipal dois', 'EEspera']);
    expect(screen.getByRole('columnheader', { name: /#/ }).getAttribute('aria-sort')).toBe('ascending');
  });

  it.each([
    { selection: 'Gomes', invitedBy: 'Gomes' },
    { selection: '', invitedBy: null },
  ])('salva a seleção de convidador ($selection)', async ({ selection, invitedBy }) => {
    window.history.replaceState({}, '', '/#games?date=2026-12-02');
    render(<App/>);
    fireEvent.click(await screen.findByRole('button', { name: 'Editar participação de Principal dois' }));
    const dialog = within(screen.getByRole('dialog', { name: 'Participação de Principal dois' }));
    const inviter = dialog.getByRole('combobox', { name: 'Convidado por' }) as HTMLSelectElement;
    expect(inviter.value).toBe('Apelido da lista antiga');
    await dialog.findByRole('option', { name: 'Gomes' });
    fireEvent.change(inviter, { target: { value: selection } });
    fireEvent.click(dialog.getByRole('button', { name: 'Salvar alterações' }));
    await waitFor(() => {
      const patch = requests.find(({ path, init }) => path === '/api/games/game/entries/main-2' && init?.method === 'PATCH');
      expect(JSON.parse(String(patch?.init?.body ?? '{}'))).toEqual({ invited_by: invitedBy, prebuilt_team_number: null });
    });
  });

  it('mantém convidado como identidade da cobrança e filtra a dívida pelo convidante', async () => {
    window.history.replaceState({}, '', '/#charges');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const body = path === '/api/session'
        ? { authenticated: true, user: { uid: 'admin', username: 'gestor', name: 'Gestor', is_admin: true } }
        : path === '/api/charges'
          ? { items: [
            { id: 'guest-open', person_id: 'thiago', name: 'Thiago Sousa', type: 'single', reference_date: '2026-11-11', amount_cents: 750, status: 'pending', debtor_person_id: 'pyu', debtor_name: 'Pyu', invited_by: 'Pyu' },
            { id: 'thiago-august', person_id: 'thiago-guest', name: 'Thiago', type: 'single', reference_date: '2026-08-19', amount_cents: 750, status: 'pending', debtor_person_id: 'elissandro', debtor_name: 'Elissandro', invited_by: 'Elissandro' },
            { id: 'elissandro-august', person_id: 'elissandro', name: 'Elissandro', type: 'single', reference_date: '2026-08-19', amount_cents: 750, status: 'pending', debtor_person_id: 'elissandro', debtor_name: 'Elissandro' },
            { id: 'paid', person_id: 'allan', name: 'Allan', type: 'single', reference_date: '2026-11-11', amount_cents: 1500, status: 'paid', debtor_person_id: 'allan', debtor_name: 'Allan' },
          ], total_cents: 3750 }
          : path === '/api/debtors'
            ? { items: [
              { person_id: 'pyu', name: 'Pyu', amount_cents: 750, count: 1 },
              { person_id: 'elissandro', name: 'Elissandro', amount_cents: 1500, count: 2 },
            ], total_cents: 2250 }
            : { items: [] };
      return { ok: true, json: async () => body };
    }));
    render(<App/>);

    await screen.findByRole('heading', { name: 'Dívidas por jogador' });
    fireEvent.click(await screen.findByRole('button', { name: 'Filtrar cobranças de Elissandro' }));
    expect(screen.getByText('Thiago')).toBeTruthy();
    expect(screen.getByText('Convidado por Elissandro')).toBeTruthy();
    const guestRow = screen.getByRole('row', { name: /Abrir partida de Thiago/ });
    const ownRow = screen.getByRole('row', { name: /Abrir partida de Elissandro/ });
    expect(within(guestRow).getByText('Convidado')).toBeTruthy();
    expect(within(ownRow).getByText('Convidado')).toBeTruthy();
    const table = screen.getByRole('table', { name: 'Cobranças e pagamentos' });
    fireEvent.click(within(table).getByRole('button', { name: 'Tipo' }));
    const typeFilter = within(table).getByRole('combobox', { name: 'Filtrar Tipo — Cobranças e pagamentos' });
    expect(within(typeFilter).getAllByRole('option').map(option => option.textContent)).toEqual(['Todos', 'Mensalidade', 'Convidado']);
    fireEvent.click(guestRow);
    expect(location.hash).toBe('#games?date=2026-08-19&person_id=thiago-guest');
  });

  it('abre filtros das tabelas pelo título e pesquisa a posição sem intervalo numérico', async () => {
    window.history.replaceState({}, '', '/#games');
    render(<App/>);
    const table = await screen.findByRole('table', { name: 'Participantes da partida' });
    expect(within(table).queryByRole('searchbox', { name: 'Filtrar # — Participantes da partida' })).toBeNull();
    expect(within(table).queryByRole('spinbutton')).toBeNull();

    fireEvent.click(within(table).getByRole('button', { name: '#' }));
    expect(within(table).getByRole('searchbox', { name: 'Filtrar # — Participantes da partida' })).toBeTruthy();
    expect(within(table).queryByRole('spinbutton')).toBeNull();

    fireEvent.click(within(table).getByRole('button', { name: 'Tipo' }));
    const typeFilter = within(table).getByRole('combobox', { name: 'Filtrar Tipo — Participantes da partida' });
    expect(within(typeFilter).getByRole('option', { name: 'Assinante' })).toBeTruthy();
    expect(within(typeFilter).getByRole('option', { name: 'Convidado' })).toBeTruthy();
  });

  it('abre a lista semanal ou mensal correspondente ao clicar numa cobrança', async () => {
    window.history.replaceState({}, '', '/#charges');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const body = path === '/api/session'
        ? { authenticated: true, user: { uid: 'admin', username: 'gestor', name: 'Gestor', is_admin: true } }
        : path === '/api/charges'
          ? { items: [
            { id: 'single', person_id: 'p', name: 'Gabriel Magalhães', type: 'single', reference_date: '2026-09-02', amount_cents: 750, status: 'pending' },
            { id: 'monthly', person_id: 'p', name: 'Gabriel Magalhães', type: 'monthly', reference_date: '2026-09-01', amount_cents: 1250, status: 'pending' },
          ], total_cents: 2000 }
          : path === '/api/debtors' ? { items: [], total_cents: 0 } : { items: [] };
      return { ok: true, json: async () => body };
    }));
    render(<App/>);

    fireEvent.click(await screen.findByRole('row', { name: /Abrir partida de Gabriel Magalhães/ }));
    expect(location.hash).toBe('#games?date=2026-09-02&person_id=p');

    window.location.hash = '#charges';
    fireEvent.click(await screen.findByRole('row', { name: /Abrir mensalidade de Gabriel Magalhães/ }));
    expect(location.hash).toBe('#monthly?period=2026-09&person_id=p');
  });

  it('rola até a entrada da pessoa ao abrir a lista pela cobrança semanal', async () => {
    window.history.replaceState({}, '', '/#charges');
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scrollIntoView });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const body = path === '/api/session'
        ? { authenticated: true, user: { uid: 'admin', username: 'gestor', name: 'Gestor', is_admin: true } }
        : path === '/api/charges'
          ? { items: [{ id: 'charge', person_id: 'tiago-id', name: 'Tiago', type: 'single', reference_date: '2026-11-11', amount_cents: 750, status: 'pending' }] }
          : path === '/api/debtors'
            ? { items: [], total_cents: 0 }
            : path === '/api/games'
              ? { items: [{ id: 'game', game_date: '2026-11-11', starts_at: '2026-11-11T19:30:00-03:00', cutoff_at: '2026-11-11T16:00:00-03:00', capacity: 24, main_count: 1, waiting_count: 0 }] }
              : path === '/api/games/game'
                ? { id: 'game', game_date: '2026-11-11', starts_at: '2026-11-11T19:30:00-03:00', cutoff_at: '2026-11-11T16:00:00-03:00', capacity: 24, main_count: 1, waiting_count: 0, entries: [{ id: 'entry', person_id: 'tiago-id', name: 'Tiago', status: 'main', position: 1, is_monthly_subscriber: false, owes_single_payment: false }] }
                : { items: [] };
      return { ok: true, json: async () => body };
    }));
    render(<App/>);

    fireEvent.click(await screen.findByRole('row', { name: /Abrir partida de Tiago/ }));
    const row = await waitFor(() => {
      const target = document.getElementById('weekly-entry-tiago-id');
      expect(target).toBeTruthy();
      expect(scrollIntoView).toHaveBeenCalled();
      expect(target?.classList.contains('entry-targeted')).toBe(true);
      return target;
    });
    expect(row?.querySelector('[data-label="Jogador"]')?.textContent).toContain('Tiago');
    expect(location.hash).toBe('#games?date=2026-11-11');
  });

  it('abre a mensagem de origem e navega pelo histórico mensal', async () => {
    window.history.replaceState({}, '', '/#monthly?period=2026-11');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const body = path === '/api/session'
        ? { authenticated: true, user: { uid: 'admin', username: 'gestor', name: 'Gestor', is_admin: true } }
        : path === '/api/charges?type=monthly'
          ? { items: [{ reference_date: '2026-11-01' }] }
          : path === '/api/monthly?month=11&year=2026'
            ? { items: [
              { id: 'fulano', person_id: 'fulano', name: 'fulano', position: 1, month: 11, year: 2026, has_paid: false, amount_cents: 1250, charge_id: 'charge-1', has_source: true, source_message_id: 'message-2' },
              { id: 'pyu', person_id: 'pyu', name: 'pyu', position: 2, month: 11, year: 2026, has_paid: false, amount_cents: 1250, charge_id: 'charge-2', has_source: true, source_message_id: 'message-2' },
            ] }
            : path === '/api/source-history/monthly?month=11&year=2026'
              ? { items: [
                { id: 'message-1', occurred_at: '2026-11-01T12:00:00-03:00', sender_name: 'Pyu', text: 'LISTA DE ASSINANTES DO MÊS DE NOVEMBRO\n1. pyu ✅', status: 'applied' },
                { id: 'message-2', occurred_at: '2026-11-02T12:00:00-03:00', sender_name: 'Fulano', text: 'LISTA DE ASSINANTES DO MÊS DE NOVEMBRO\n1. pyu (conv.) ✅\n2. fulano', status: 'applied' },
              ] }
              : { items: [] };
      return { ok: true, json: async () => body };
    }));
    render(<App/>);
    const sourceButton = await screen.findByRole('button', { name: 'Ver mensagem de origem de pyu' });
    fireEvent.click(sourceButton);
    const dialog = await screen.findByRole('dialog', { name: 'Histórico da lista mensal' });
    await waitFor(() => expect(dialog.querySelector('.source-history-text')?.textContent).toContain('1. pyu ✅'));
    expect(dialog.querySelector('.source-player-highlight')?.textContent).toBe('1. pyu ✅');
    expect(within(dialog).getByRole('button', { name: 'Primeira aparição' }).hasAttribute('disabled')).toBe(true);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Última aparição' }));
    await waitFor(() => expect(dialog.querySelector('.source-history-text')?.textContent).toContain('2. fulano'));
    expect(within(dialog).getByText('2 de 2')).toBeTruthy();
  });

  it('encontra a primeira e a última aparição do jogador clicado quando as entradas compartilham a mesma fonte', async () => {
    window.history.replaceState({}, '', '/#games?date=2026-11-11');
    const game = { id: 'game', game_date: '2026-11-11', starts_at: '2026-11-11T19:30:00-03:00', cutoff_at: '2026-11-11T16:00:00-03:00', capacity: 24, main_count: 2, waiting_count: 0 };
    const entries = [
      { id: 'pyu', person_id: 'pyu', name: 'Pyu', status: 'main', position: 1, is_monthly_subscriber: true, owes_single_payment: false, has_source: true, source_message_id: 'weekly-47' },
      { id: 'thyago', person_id: 'thyago', name: 'Thyago', status: 'main', position: 21, is_monthly_subscriber: false, owes_single_payment: true, invited_by: 'Viegas', has_source: true, source_message_id: 'weekly-47' },
    ];
    const messages = Array.from({ length: 47 }, (_, index) => {
      const number = index + 1;
      const sender = number === 12 ? 'Viégas' : 'Pyu';
      const entry = number === 12 ? '\nConvidados\n1. Thyago'
        : number === 47 ? '\n 21.⁠ ⁠Thyago2️⃣ (conv)'
        : '\n5. Thyago Almeida';
      return {
        id: `weekly-${number}`, occurred_at: '2026-11-09T12:00:00-03:00', sender_name: sender,
        chat_id: 'fred-export-history', text: `LISTA VÔLEI FREDERICO 11/11\n1. Pyu${entry}`, status: 'applied',
        message_type: 'weekly_attendance',
      };
    });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const body = path === '/api/session'
        ? { authenticated: true, user: { uid: 'admin', username: 'gestor', name: 'Gestor', is_admin: true } }
        : path === '/api/games'
          ? { items: [game] }
          : path === '/api/games/game'
            ? { ...game, entries }
            : path === '/api/source-history/weekly?game_date=2026-11-11'
              ? { items: messages }
              : { items: [] };
      return { ok: true, json: async () => body };
    }));
    render(<App/>);
    fireEvent.click(await screen.findByRole('button', { name: 'Ver mensagem de origem de Thyago' }));
    const dialogElement = await screen.findByRole('dialog', { name: 'Histórico da lista de 11/11/2026' });
    const dialog = within(dialogElement);
    await dialog.findByText('12 de 47');
    expect(dialog.getByText('Viégas')).toBeTruthy();
    expect(dialogElement.querySelector('.source-player-highlight')?.textContent).toBe('1. Thyago');
    expect(dialogElement.querySelectorAll('.source-player-highlight')).toHaveLength(1);

    const sourceText = dialogElement.querySelector('.source-history-text') as HTMLPreElement;
    sourceText.scrollTop = 72;
    const next = dialog.getByRole('button', { name: 'Próxima mensagem' });
    fireEvent.click(next);
    expect(dialog.getByText('13 de 47')).toBeTruthy();
    expect(dialog.getByRole('button', { name: 'Próxima mensagem' })).toBe(next);
    expect(dialogElement.querySelector('.source-history-text')).toBe(sourceText);
    expect(sourceText.scrollTop).toBe(72);
    fireEvent.click(dialog.getByRole('button', { name: 'Última aparição' }));
    expect(dialog.getByText('47 de 47')).toBeTruthy();
    expect(dialogElement.querySelector('.source-player-highlight')?.textContent).toContain('Thyago2️⃣');
    fireEvent.click(dialog.getByRole('button', { name: 'Primeira aparição' }));
    expect(dialog.getByText('12 de 47')).toBeTruthy();
  });

  it('mostra a numeração do WhatsApp por seção na tabela da partida', async () => {
    window.history.replaceState({}, '', '/#games?date=2026-11-18');
    const game = { id: 'game', game_date: '2026-11-18', starts_at: '2026-11-18T19:30:00-03:00', capacity: 24 };
    const entries = [
      { id: 'gomes', name: 'Gomes', status: 'main', position: 23, source_section: 'main', source_position: 6 },
      { id: 'sophia', name: 'Sophia', status: 'waiting', position: 24, source_section: 'guests', source_position: 4 },
      { id: 'murilo', name: 'Murilo', status: 'waiting', position: 21, source_section: 'main', source_position: 4 },
      { id: 'paulo', name: 'Paulo', status: 'main', position: 7, source_section: 'guests', source_position: 1 },
      { id: 'klesley', name: 'Klesley', status: 'main', position: 22, source_section: 'main', source_position: 5 },
    ].map(entry => ({ ...entry, person_id: entry.id, is_monthly_subscriber: entry.source_section === 'main', owes_single_payment: false }));
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const body = path === '/api/session'
        ? { authenticated: true, user: { uid: 'admin', username: 'gestor', name: 'Gestor', is_admin: true } }
        : path === '/api/games' ? { items: [game] }
          : path === '/api/games/game' ? { ...game, entries }
            : { items: [] };
      return { ok: true, json: async () => body };
    }));
    render(<App/>);
    const table = within(await screen.findByRole('table', { name: 'Participantes da partida' }));
    const participantRows = () => table.getAllByRole('row').slice(1).map(row =>
      within(row).getAllByRole('cell').slice(0, 3).map(cell =>
        cell.querySelector('.profile-name-link')?.textContent
          ?? cell.querySelector('strong')?.textContent
          ?? cell.textContent,
      ),
    );
    const sourceOrder = [
      ['4', 'Murilo', 'Espera'],
      ['5', 'Klesley', 'Principal'],
      ['6', 'Gomes', 'Principal'],
      ['1', 'Paulo', 'Principal'],
      ['4', 'Sophia', 'Espera'],
    ];
    expect(participantRows()).toEqual(sourceOrder);

    fireEvent.click(table.getByRole('button', { name: 'Ordenar # — Participantes da partida: decrescente' }));
    expect(participantRows()).toEqual([...sourceOrder].reverse());
    fireEvent.click(table.getByRole('button', { name: 'Ordenar # — Participantes da partida: ordem original' }));
    expect(participantRows()).toEqual(sourceOrder);

    fireEvent.click(table.getByRole('button', { name: '#' }));
    fireEvent.change(table.getByRole('searchbox', { name: 'Filtrar # — Participantes da partida' }), { target: { value: '4' } });
    expect(participantRows()).toEqual([sourceOrder[0], sourceOrder[4]]);
  });

  it('troca o jogador da entrada semanal selecionando outro cadastro', async () => {
    window.history.replaceState({}, '', '/#games?date=2026-12-02');
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const body = path === '/api/session'
        ? { authenticated: true, user: { uid: 'admin', username: 'gestor', name: 'Gestor', is_admin: true } }
        : path === '/api/games'
          ? { items: [{ id: 'game', game_date: '2026-12-02', starts_at: '2026-12-02T19:30:00-03:00', cutoff_at: '2026-12-02T16:00:00-03:00', capacity: 24, main_count: 1, waiting_count: 0 }] }
          : path === '/api/games/game'
            ? { id: 'game', game_date: '2026-12-02', starts_at: '2026-12-02T19:30:00-03:00', cutoff_at: '2026-12-02T16:00:00-03:00', capacity: 24, main_count: 1, waiting_count: 0, entries: [{ id: 'entry', person_id: 'old', name: 'Jogador antigo', status: 'main', position: 1, is_monthly_subscriber: false, owes_single_payment: true }] }
            : path === '/api/people'
              ? { items: [{ id: 'old', name: 'Jogador antigo', active: true }, { id: 'new', name: 'Jogador novo', active: true }] }
              : { ok: true };
      return { ok: true, json: async () => body };
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App/>);

    const summary = (await screen.findByText('02/12/2026 · 19:30')).parentElement?.parentElement;
    expect(summary?.firstElementChild?.className).toContain('game-detail-summary');
    expect(screen.queryByText('VÔLEI DE QUARTA')).toBeNull();
    expect(summary?.children[1]?.className).toContain('game-count');
    const headerActions = screen.getByRole('button', { name: 'Histórico do WhatsApp' }).parentElement;
    expect(headerActions?.className).toContain('games-list-actions');
    expect(headerActions?.children).toHaveLength(2);

    const swapPlayerButton = await screen.findByRole('button', { name: 'Trocar jogador de Jogador antigo' });
    expect(swapPlayerButton.querySelector('svg')?.getAttribute('width')).toBe('16');
    expect(swapPlayerButton.querySelector('svg')?.classList).toContain('lucide-users-round-collaboration');
    fireEvent.click(swapPlayerButton);
    const dialog = await screen.findByRole('dialog', { name: 'Trocar jogador de Jogador antigo' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Selecione um jogador' }));
    fireEvent.change(within(dialog).getByRole('searchbox', { name: 'Pesquisar jogador' }), { target: { value: 'novo' } });
    fireEvent.click(within(dialog).getByRole('option', { name: 'Jogador novo' }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Trocar jogador' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/games/game/entries/entry/player', expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ person_id: 'new' }) })));
  });

  it('resume eventos semânticos, agrupa convidados e mostra a primeira mensagem como diff', async () => {
    window.history.replaceState({}, '', '/#audit');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const items = [
        {
          id: 'whatsapp', occurred_at: '2026-11-17T20:00:00-03:00', source: 'whatsapp', actor_name: 'WhatsApp',
          action: 'list_change', entity_type: 'whatsapp_list', status: 'applied',
          changes: [
            { kind: 'weekly_added', reference_date: '2026-11-18', people: [{ id: 'bia', name: 'Bia', is_actor: true }] },
            { kind: 'guest_added', reference_date: '2026-11-18', people: [{ id: 'ana', name: 'Ana' }] },
            { kind: 'guest_added', reference_date: '2026-11-18', people: [{ id: 'beto', name: 'Beto' }] },
            { kind: 'subscription_added', reference_date: '2026-11-01', people: [{ id: 'bia', name: 'Bia', is_actor: true }] },
            { kind: 'weekly_removed', reference_date: '2026-11-18', people: [{ id: 'caio', name: 'Caio' }] },
            { kind: 'subscription_removed', reference_date: '2026-11-01', people: [{ id: 'duda', name: 'Duda' }] },
            { kind: 'guest_removed', reference_date: '2026-11-18', people: [{ id: 'eva', name: 'Eva' }] },
            { kind: 'monthly_paid', reference_date: '2026-11-01', people: [{ id: 'bia', name: 'Bia' }] },
            { kind: 'guest_paid', reference_date: '2026-11-18', people: [{ id: 'ana', name: 'Ana' }] },
            { kind: 'alias_added', alias: 'Biazinha', people: [{ id: 'bia', name: 'Bia' }] },
          ],
          message_diff: { before: null, after: 'Lista de quarta\nBia\nConvidados: Ana e Beto' },
        },
        {
          id: 'site', occurred_at: '2026-11-17T19:00:00-03:00', source: 'panel', actor_name: 'Gestor',
          action: 'replace_player', entity_type: 'weekly', before: { name: 'Jogador antigo', game_date: '2026-11-18' },
          after: { name: 'Jogador novo', game_date: '2026-11-18' },
          changes: [{ kind: 'player_replaced', reference_date: '2026-11-18', people: [{ id: 'old', name: 'Jogador antigo' }, { id: 'new', name: 'Jogador novo' }] }],
        },
        {
          id: 'legacy', occurred_at: '2026-11-17T18:00:00-03:00', source: 'panel', actor_name: 'Gestor',
          action: 'update', entity_type: 'person', before: { name: 'Nome antigo', active: true }, after: { name: 'Nome novo', active: false },
        },
      ];
      const body = path === '/api/session'
        ? { authenticated: true, user: { uid: 'admin', username: 'gestor', name: 'Gestor', is_admin: true } }
        : path === '/api/audit?limit=100' ? { items }
          : path === '/api/people' ? { items: [] }
            : { items: [] };
      return { ok: true, json: async () => body };
    }));
    render(<App/>);

    await screen.findByText('Bia adicionou o próprio nome à lista principal em 18/11/2026.');
    expect(screen.getByText('Convidados adicionados à lista de convidados: Ana e Beto · 18/11/2026.')).toBeTruthy();
    expect(screen.getByText('Bia adicionou o próprio nome à lista de assinantes de novembro de 2026.')).toBeTruthy();
    expect(screen.getByText('Jogadores removidos da lista principal: Caio · 18/11/2026.')).toBeTruthy();
    expect(screen.getByText('Assinantes removidos da lista de assinantes: Duda · novembro de 2026.')).toBeTruthy();
    expect(screen.getByText('Convidados removidos da lista de convidados: Eva · 18/11/2026.')).toBeTruthy();
    expect(screen.getByText('WhatsApp confirmou a mensalidade de Bia referente a novembro de 2026.')).toBeTruthy();
    expect(screen.getByText('WhatsApp confirmou o pagamento de convidado de Ana do dia 18/11/2026.')).toBeTruthy();
    expect(screen.getByText('Bia: apelido adicionado “Biazinha”.')).toBeTruthy();
    expect(screen.getByText('Jogador substituído: Jogador antigo → Jogador novo · 18/11/2026.')).toBeTruthy();
    expect(screen.getByText('Nome: Nome antigo → Nome novo')).toBeTruthy();

    const firstMessageEvent = screen.getByText('Lista atualizada', { selector: 'strong' }).closest('.audit-item') as HTMLElement;
    fireEvent.click(within(firstMessageEvent).getByText('Ver alteração'));
    expect(within(firstMessageEvent).getByText(/Primeira mensagem registrada/)).toBeTruthy();
    expect(within(firstMessageEvent).getByText('+ Lista de quarta')).toBeTruthy();
    expect(within(firstMessageEvent).queryByText(/"kind"/)).toBeNull();

    const legacyEvent = screen.getByText('Dados atualizados', { selector: 'strong' }).closest('.audit-item') as HTMLElement;
    fireEvent.click(within(legacyEvent).getByText('Ver alteração'));
    const legacyDetails = legacyEvent.querySelector('details') as HTMLElement;
    expect(within(legacyDetails).getByText('Antes')).toBeTruthy();
    expect(within(legacyDetails).getByText('Depois')).toBeTruthy();
    expect(within(legacyDetails).getByText('Nome antigo')).toBeTruthy();
    expect(within(legacyDetails).getByText('Nome novo')).toBeTruthy();
    expect(within(legacyDetails).queryByText('Nome: Nome antigo → Nome novo')).toBeNull();
  });

  it('mantém o resumo sem detalhes expansíveis no histórico compacto do overview', async () => {
    window.history.replaceState({}, '', '/#overview');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const body = path === '/api/session'
        ? { authenticated: true, user: { uid: 'admin', username: 'gestor', name: 'Gestor', is_admin: true } }
        : path === '/api/games' ? { items: [] }
          : path === '/api/monthly?month=11&year=2026' ? { items: [] }
            : path === '/api/debtors' ? { items: [], total_cents: 0 }
            : path === '/api/audit?limit=10' ? { items: [{
                id: 'compact', occurred_at: '2026-11-17T20:00:00-03:00', source: 'whatsapp', action: 'list_change', entity_type: 'whatsapp_list',
                changes: [{ kind: 'guest_added', reference_date: '2026-11-18', people: [{ id: 'ana', name: 'Ana' }, { id: 'beto', name: 'Beto' }] }],
              }] }
                : { items: [] };
      return { ok: true, json: async () => body };
    }));
    render(<App/>);

    const compactEvent = await screen.findByText('Convidados adicionados à lista de convidados: Ana e Beto · 18/11/2026.');
    expect(compactEvent.closest('.audit-list')?.className).toContain('compact');
    expect(screen.queryByText('Ver alteração')).toBeNull();
  });

  it('usa a sessão devolvida pelo login de email ou usuário e senha', async () => {
    window.history.replaceState({}, '', '/');
    const fetchLogin = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === '/api/auth/login' && init?.method === 'POST') {
        return { ok: true, json: async () => ({
          status: 'authenticated',
          session: { authenticated: true, user: { uid: 'player', username: 'jogador', name: 'Jogador', is_admin: false } },
        }) };
      }
      const body = path === '/api/session'
        ? { authenticated: false, user: null }
        : { items: [] };
      return { ok: true, json: async () => body };
    });
    vi.stubGlobal('fetch', fetchLogin);
    render(<App/>);

    const submit = await screen.findByRole('button', { name: 'Entrar' });
    const loginForm = screen.getByRole('form', { name: 'Entrar no Fred' });
    const signupSwitch = within(loginForm).getByRole('button', { name: 'Criar conta' });
    const google = screen.getByRole('link', { name: 'Continuar com Google' });
    expect(loginForm.contains(signupSwitch)).toBe(true);
    expect(Boolean(submit.compareDocumentPosition(signupSwitch) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
    expect(Boolean(signupSwitch.compareDocumentPosition(google) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
    expect(google.getAttribute('href')).toBe('/api/auth/google');
    expect(Boolean(submit.compareDocumentPosition(google) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
    expect(Array.from(document.querySelectorAll('.sports-patterns img'), icon => icon.getAttribute('src'))).toEqual([
      '/sports/volleyball.svg', '/sports/basketball.svg', '/sports/tennis.svg',
    ]);

    fireEvent.change(screen.getByRole('textbox', { name: 'Email ou usuário' }), { target: { value: 'jogador' } });
    fireEvent.change(screen.getByLabelText('Senha'), { target: { value: 'senha de teste' } });
    fireEvent.click(submit);
    await screen.findByRole('link', { name: 'Meu painel' });

    const sent = fetchLogin.mock.calls.find(([path, init]) => path === '/api/auth/login' && init?.method === 'POST')?.[1];
    expect(sent?.body).toBe(JSON.stringify({ identifier: 'jogador', password: 'senha de teste' }));
    expect(new Headers(sent?.headers).get('X-Fred-Request')).toBe('1');
    expect(fetchLogin.mock.calls.filter(([path]) => path === '/api/session')).toHaveLength(1);
  });

  it('cria uma conta pelo formulário e permite voltar ao login', async () => {
    window.history.replaceState({}, '', '/');
    const submitted: { path: string; body?: BodyInit | null }[] = [];
    const fetchSignup = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      submitted.push({ path, body: init?.body });
      const body = path === '/api/session'
        ? { authenticated: false, user: null, signup_url: '/api/auth/signup' }
        : path === '/api/auth/username-availability'
          ? { username: String(JSON.parse(String(init?.body)).name).toLowerCase().replace(/[^a-z0-9_.-]+/g, '-'), available: JSON.parse(String(init?.body)).name !== 'Nome ocupado' }
        : { status: 'confirmation_sent' };
      return { ok: true, json: async () => body };
    });
    vi.stubGlobal('fetch', fetchSignup);
    render(<App/>);

    fireEvent.click(await screen.findByRole('button', { name: 'Criar conta' }));
    const signupForm = screen.getByRole('form', { name: 'Criar conta no Fred' });
    const backToLogin = within(signupForm).getByRole('button', { name: 'Fazer login' });
    const signupSubmit = within(signupForm).getByRole('button', { name: 'Criar conta' });
    const signupGoogle = screen.getByRole('link', { name: 'Continuar com Google' });
    expect(signupForm.contains(backToLogin)).toBe(true);
    expect(Boolean(signupSubmit.compareDocumentPosition(backToLogin) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
    expect(Boolean(backToLogin.compareDocumentPosition(signupGoogle) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
    fireEvent.click(backToLogin);
    expect(screen.getByRole('form', { name: 'Entrar no Fred' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Criar conta' }));
    expect(screen.getByRole('link', { name: 'Continuar com Google' }).getAttribute('href')).toBe('/api/auth/google');

    const signupPassword = screen.getByLabelText('Senha') as HTMLInputElement;
    const signupPasswordRepeat = screen.getByLabelText('Confirme a senha') as HTMLInputElement;
    expect(signupPassword.type).toBe('password');
    expect(signupPasswordRepeat.type).toBe('password');
    fireEvent.click(screen.getByRole('button', { name: 'Mostrar senha' }));
    expect(signupPassword.type).toBe('text');
    expect(signupPasswordRepeat.type).toBe('password');
    fireEvent.click(screen.getByRole('button', { name: 'Mostrar confirmação de senha' }));
    expect(signupPasswordRepeat.type).toBe('text');
    fireEvent.click(screen.getByRole('button', { name: 'Ocultar senha' }));
    expect(signupPassword.type).toBe('password');

    fireEvent.change(screen.getByLabelText('Nome'), { target: { value: 'Nome ocupado' } });
    expect(await screen.findByText('Esse nome de usuário já existe. Escolha outro.')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Criar conta' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Nome'), { target: { value: 'Jogador Novo' } });
    expect(await screen.findByText('Nome de usuário disponível.')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'novo@example.test' } });
    fireEvent.change(screen.getByLabelText('Senha'), { target: { value: 'senha-segura-123' } });
    fireEvent.change(screen.getByLabelText('Confirme a senha'), { target: { value: 'senha-divergente' } });
    fireEvent.click(screen.getByRole('button', { name: 'Criar conta' }));
    expect((await screen.findByRole('alert')).textContent).toContain('As senhas não conferem.');
    expect(fetchSignup.mock.calls.some(([path]) => path === '/api/auth/signup')).toBe(false);

    fireEvent.change(screen.getByLabelText('Confirme a senha'), { target: { value: 'senha-segura-123' } });
    fireEvent.click(screen.getByRole('button', { name: 'Criar conta' }));
    expect(await screen.findByText(/Enviamos um email para confirmar seu cadastro\./)).toBeTruthy();

    const signupRequest = submitted.find(({ path }) => path === '/api/auth/signup');
    expect(signupRequest?.path).toBe('/api/auth/signup');
    expect(JSON.parse(String(signupRequest?.body))).toEqual({
      name: 'Jogador Novo', email: 'novo@example.test', password: 'senha-segura-123', password_repeat: 'senha-segura-123',
    });
    fireEvent.click(screen.getByRole('button', { name: 'Voltar para entrar' }));
    expect(screen.getByRole('form', { name: 'Entrar no Fred' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Fazer login' })).toBeNull();
  });

  it('oferece a página do Authentik quando o login pede uma verificação adicional', async () => {
    window.history.replaceState({}, '', '/');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const body = String(input) === '/api/session'
        ? { authenticated: false, user: null, login_url: '/api/auth/login' }
        : { status: 'hosted_login_required' };
      return { ok: true, json: async () => body };
    }));
    render(<App/>);

    const submit = await screen.findByRole('button', { name: 'Entrar' });
    fireEvent.change(screen.getByRole('textbox', { name: 'Email ou usuário' }), { target: { value: 'jogador@example.test' } });
    fireEvent.change(screen.getByLabelText('Senha'), { target: { value: 'senha de teste' } });
    fireEvent.click(submit);

    const hosted = await screen.findByRole('link', { name: 'página segura de login' });
    expect(hosted.getAttribute('href')).toBe('/api/auth/login');
    expect((screen.getByLabelText('Senha') as HTMLInputElement).value).toBe('');
  });

  it('confirma a exclusão do cadastro local de uma conta', async () => {
    window.history.replaceState({}, '', '/#accounts');
    let accountDeleted = false;
    const deleteRequest = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === '/api/session') {
        return { ok: true, json: async () => ({ authenticated: true, user: { uid: 'admin', username: 'admin', name: 'Gestor', is_admin: true } }) };
      }
      if (path === '/api/accounts') {
        return { ok: true, json: async () => ({ items: accountDeleted ? [] : [{ uid: 'player-uid', username: 'player', name: 'Jogador', email: 'player@example.test', is_admin: false, person_id: null }] }) };
      }
      if (path === '/api/people') return { ok: true, json: async () => ({ items: [] }) };
      if (path === '/api/accounts/player-uid' && init?.method === 'DELETE') {
        accountDeleted = true;
        return { ok: true, json: async () => ({ ok: true }) };
      }
      return { ok: true, json: async () => ({ items: [] }) };
    });
    vi.stubGlobal('fetch', deleteRequest);
    render(<App/>);

    fireEvent.click(await screen.findByRole('button', { name: 'Gerenciar acesso' }));
    expect(screen.getByText(/o acesso no Authentik precisa ser removido separadamente/i)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Excluir conta' }));
    expect(screen.getByRole('dialog', { name: 'Excluir conta do Fred?' })).toBeTruthy();
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Excluir conta do Fred?' })).getByRole('button', { name: 'Cancelar' }));
    expect(deleteRequest.mock.calls.some(([path, init]) => String(path) === '/api/accounts/player-uid' && init?.method === 'DELETE')).toBe(false);

    fireEvent.click(screen.getByRole('button', { name: 'Gerenciar acesso' }));
    fireEvent.click(screen.getByRole('button', { name: 'Excluir conta' }));
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Excluir conta do Fred?' })).getByRole('button', { name: 'Confirmar' }));
    await waitFor(() => expect(deleteRequest.mock.calls.some(([path, init]) => String(path) === '/api/accounts/player-uid' && init?.method === 'DELETE')).toBe(true));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Gerenciar acesso' })).toBeNull());
  });
});

describe('páginas do jogador', () => {
  const setMobileViewport = (matches: boolean) => vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches,
    media: '(max-width: 760px)',
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
  const gameDate = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Sao_Paulo', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
  const game = { id: 'g1', game_date: gameDate, starts_at: `${gameDate}T19:30:00-03:00`, cutoff_at: `${gameDate}T16:00:00-03:00`, capacity: 24, main_count: 1, waiting_count: 0, can_join: true, can_leave: true, own_entry: null };
  const setup = async (hash = '#player', extra: Record<string, unknown> = {}) => {
    window.history.replaceState({}, '', `/${hash}`);
    const calls: { path: string; method: string }[] = [];
    let joined = false;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input); const method = init?.method ?? 'GET'; calls.push({ path, method });
      if (path === '/api/me/games/g1/join') joined = method === 'POST';
      let body: unknown = { items: [] };
      if (path === '/api/session') body = { authenticated: true, user: extra.manager ? { uid: 'manager', username: 'gestor', name: 'Gestor', is_admin: true, person_id: 'p1' } : { uid: 'player', username: 'jogador', name: 'Jogador', is_admin: false, person_id: 'p1' } };
      else if (path === '/api/me') body = { person: { id: 'p1', name: 'Jogador' }, monthly: [], charges: extra.charges ?? [], games: extra.meGames ?? [], history: [], can_manage: false };
      else if (path === '/api/me/games') body = { items: [extra.game ?? game] };
      else if (path === '/api/me/games/g1') body = { ...(extra.gameDetail ?? extra.game ?? game), entries: extra.entries ?? [{ id: 'own', person_id: 'p1', name: 'Jogador', status: 'main', source_section: 'main', is_monthly_subscriber: true, owes_single_payment: false }, { id: 'guest', person_id: 'p2', name: 'Convidado Teste', status: 'main', source_section: 'guests', is_monthly_subscriber: false, owes_single_payment: true, can_remove: true }], own_entry: joined ? { id: 'own', person_id: 'p1', name: 'Jogador', status: 'main', is_monthly_subscriber: true, owes_single_payment: false } : null, can_add_guest: (extra.gameDetail as { can_add_guest?: boolean } | undefined)?.can_add_guest ?? (extra.game as { can_add_guest?: boolean } | undefined)?.can_add_guest ?? true };
      else if (path === '/api/me/games/g1/history') body = extra.history ?? { items: [{ id: 'm1', occurred_at: '2026-11-11T21:00:00Z', text: 'Lista semanal inicial', status: 'processed', message_type: 'weekly_attendance' }, { id: 'm2', occurred_at: '2026-11-18T21:00:00Z', text: 'Lista semanal recente', status: 'processed', message_type: 'weekly_attendance' }] };
      else if (path.startsWith('/api/me/monthly')) body = extra.monthly ?? { items: [], own_subscription: null, can_join: true, can_leave: true };
      return { ok: true, json: async () => body };
    }));
    render(<App/>);
    await screen.findByRole('button', { name: `Menu do perfil de ${extra.manager ? 'Gestor' : 'Jogador'}` });
    return calls;
  };

  it('no celular mantém Jogador e Ações, oculta # e Tipo e ativa Partidas', async () => {
    setMobileViewport(true);
    await setup('#player-games');
    const navigation = screen.getByRole('navigation', { name: 'Navegação mobile' });
    expect(within(navigation).getByRole('button', { name: 'Partidas' }).getAttribute('aria-current')).toBe('page');
    fireEvent.click(await screen.findByRole('button', { name: /Abrir lista da partida de/ }));
    const table = await screen.findByRole('table', { name: 'Participantes da partida' });
    expect(within(table).getByRole('columnheader', { name: /Jogador/ })).toBeTruthy();
    expect(within(table).getByRole('columnheader', { name: 'Ações' })).toBeTruthy();
    expect(within(table).queryByRole('columnheader', { name: /#/ })).toBeNull();
    expect(within(table).queryByRole('columnheader', { name: /Tipo/ })).toBeNull();
    expect(screen.queryByText('Deslize a tabela para ver todas as colunas.')).toBeNull();
  });

  it('retira a dica das tabelas mensal e financeira no celular, sem alterar a tabela de gestão', async () => {
    setMobileViewport(true);
    await setup('#player-monthly');
    await screen.findByRole('table', { name: 'Assinantes do mês' });
    expect(screen.queryByText('Deslize a tabela para ver todas as colunas.')).toBeNull();
    const navigation = screen.getByRole('navigation', { name: 'Navegação mobile' });
    fireEvent.click(within(navigation).getByRole('button', { name: 'Financeiro' }));
    await waitFor(() => expect(location.hash).toBe('#player-finance'));
    await screen.findByRole('table', { name: 'Minhas cobranças' });
    expect(screen.queryByText('Deslize a tabela para ver todas as colunas.')).toBeNull();

    cleanup();
    await setup('#monthly', { manager: true });
    const managerTable = await screen.findByRole('table', { name: 'Assinantes' });
    expect(within(managerTable).getByRole('columnheader', { name: /#/ })).toBeTruthy();
    expect(within(managerTable).getByRole('columnheader', { name: /Jogador/ })).toBeTruthy();
    expect(within(managerTable).getByRole('columnheader', { name: /Pagamento/ })).toBeTruthy();
    expect(screen.getByText('Deslize a tabela para ver todas as colunas.')).toBeTruthy();
  });

  it('oferece as quatro páginas do jogador e preserva o hash selecionado ao navegar', async () => {
    await setup();
    expect(await screen.findByText('Meu saldo em aberto')).toBeTruthy();
    fireEvent.click(screen.getByRole('link', { name: 'Partidas' }));
    await waitFor(() => expect(location.hash).toBe('#player-games'));
    await screen.findByRole('heading', { name: 'Partidas' });
    fireEvent.click(screen.getByRole('link', { name: 'Assinantes' }));
    await waitFor(() => expect(location.hash).toBe('#player-monthly'));
    await screen.findByRole('heading', { name: 'Assinantes' });
    fireEvent.click(screen.getByRole('link', { name: 'Financeiro' }));
    await waitFor(() => expect(location.hash).toBe('#player-finance'));
    await screen.findByRole('heading', { name: 'Financeiro' });
  });

  it('abre a partida no calendário, mostra histórico e permite adicionar/remover convidado próprio', async () => {
    const calls = await setup('#player-games');
    fireEvent.click(await screen.findByRole('button', { name: /Abrir lista da partida de/ }));
    const participants = await screen.findByRole('table', { name: 'Participantes da partida' });
    expect(within(participants).getByText('Convidado Teste')).toBeTruthy();
    expect(within(participants).queryByText('Posição')).toBeNull();
    expect(within(participants).getByRole('columnheader', { name: /Tipo/ })).toBeTruthy();
    expect(screen.getByText('Convidado')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Adicionar convidado' }));
    const dialog = screen.getByRole('dialog', { name: 'Adicionar convidado' });
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Nome do convidado' }), { target: { value: 'Novo convidado' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Adicionar convidado' }));
    await waitFor(() => expect(calls.some(call => call.path === '/api/me/games/g1/guests' && call.method === 'POST')).toBe(true));
    fireEvent.click(screen.getByRole('button', { name: 'Remover' }));
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Remover convidado?' })).getByRole('button', { name: 'Confirmar' }));
    await waitFor(() => expect(calls.some(call => call.path === '/api/me/games/g1/guests/guest' && call.method === 'DELETE')).toBe(true));
  });

  it('abre o histórico geral na última mensagem e navega pelas setas', async () => {
    await setup('#player-games');
    fireEvent.click(await screen.findByRole('button', { name: /Abrir lista da partida de/ }));
    const header = await screen.findByRole('heading', { name: /Vôlei de quarta/ });
    const controls = header.parentElement?.querySelector('.player-game-controls');
    expect(header.parentElement?.firstElementChild).toBe(header);
    expect(controls).toBeTruthy();
    const historyButton = within(controls as HTMLElement).getByRole('button', { name: 'Histórico da lista semanal' });
    const joinButton = within(controls as HTMLElement).getByRole('button', { name: 'Entrar na lista' });
    const guestButton = within(controls as HTMLElement).getByRole('button', { name: 'Adicionar convidado' });
    expect(historyButton.compareDocumentPosition(joinButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(joinButton.compareDocumentPosition(guestButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(historyButton);
    const dialog = await screen.findByRole('dialog', { name: /Histórico da lista de/ });
    await within(dialog).findByText('2 de 2');
    expect(dialog.querySelector('.source-history-text')?.textContent).toContain('Lista semanal recente');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Mensagem anterior' }));
    expect(within(dialog).getByText('1 de 2')).toBeTruthy();
    expect(dialog.querySelector('.source-history-text')?.textContent).toContain('Lista semanal inicial');
  });

  it('abre Eye na primeira aparição, destaca o nome e navega às seguintes', async () => {
    const messages = [
      { id: 'm1', occurred_at: '2026-11-04T20:00:00Z', source: 'whatsapp', text: 'Lista semanal\n1. Alias Original', status: 'processed', message_type: 'weekly_attendance' },
      { id: 'm2', occurred_at: '2026-11-11T20:00:00Z', source: 'whatsapp', text: 'Lista semanal\n1. Outra pessoa', status: 'processed', message_type: 'weekly_attendance' },
      { id: 'm3', occurred_at: '2026-11-18T20:00:00Z', source: 'whatsapp', text: 'Lista semanal\n2. Alias Original', status: 'processed', message_type: 'weekly_attendance' },
    ];
    await setup('#player-games', { history: { items: messages }, entries: [
      { id: 'guest-source', person_id: 'p2', name: 'Entrada da lista', status: 'main', source_section: 'guests', is_monthly_subscriber: false, owes_single_payment: true, has_source: true, source_message_id: 'm1', can_remove: true, history_names: ['Nome canônico', 'Alias Original'] },
    ] });
    fireEvent.click(await screen.findByRole('button', { name: /Abrir lista da partida de/ }));
    const table = await screen.findByRole('table', { name: 'Participantes da partida' });
    fireEvent.click(within(table).getByRole('button', { name: 'Ver mensagem de origem de Entrada da lista' }));
    const dialog = await screen.findByRole('dialog', { name: /Histórico da lista de/ });
    await within(dialog).findByText('1 de 3');
    expect(dialog.querySelector('.source-player-highlight')?.textContent).toBe('1. Alias Original');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Próxima mensagem' }));
    expect(within(dialog).getByText('2 de 3')).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Última aparição' }));
    expect(within(dialog).getByText('3 de 3')).toBeTruthy();
    expect(dialog.querySelector('.source-player-highlight')?.textContent).toBe('2. Alias Original');
  });

  it('mantém #, Jogador e Tipo na lista, com Eye desativado sem fonte', async () => {
    await setup('#player-games');
    fireEvent.click(await screen.findByRole('button', { name: /Abrir lista da partida de/ }));
    const table = await screen.findByRole('table', { name: 'Participantes da partida' });
    expect(within(table).getByRole('columnheader', { name: /#/ })).toBeTruthy();
    expect(within(table).getByRole('columnheader', { name: /Jogador/ })).toBeTruthy();
    expect(within(table).getByRole('columnheader', { name: /Tipo/ })).toBeTruthy();
    expect(within(table).queryByRole('columnheader', { name: 'Posição' })).toBeNull();
    expect((within(table).getByRole('button', { name: 'Fonte indisponível para Jogador' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('abre filtros de Data, Minha inscrição e Tipo ao tocar nos rótulos do painel', async () => {
    const pastGame = { ...game, game_date: '2020-01-01', starts_at: '2020-01-01T19:30:00-03:00', own_entry: { id: 'own', person_id: 'p1', name: 'Jogador', status: 'main', is_monthly_subscriber: true, owes_single_payment: false } };
    await setup('#player', { meGames: [pastGame] });
    const filters = await screen.findByRole('group', { name: 'Filtros e ordenação — Minhas participações' });
    fireEvent.click(within(filters).getByRole('button', { name: 'Minha inscrição' }));
    expect(within(filters).getByRole('combobox', { name: 'Filtrar Minha inscrição — Minhas participações' })).toBeTruthy();
    fireEvent.click(within(filters).getByRole('button', { name: 'Data' }));
    expect(within(filters).getByRole('combobox', { name: 'Filtrar Data — Minhas participações, de' })).toBeTruthy();
    fireEvent.click(within(filters).getByRole('button', { name: 'Tipo' }));
    expect(within(filters).getByRole('combobox', { name: 'Filtrar Tipo — Minhas participações' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Histórico dos meus dados' })).toBeNull();
    expect(document.querySelector('.overview-grid.lower')).toBeNull();
  });

  it('mantém o botão mensal no cabeçalho junto ao seletor de mês e remove a orientação fixa', async () => {
    await setup('#player-monthly');
    const subscribe = await screen.findByRole('button', { name: 'Assinar este mês' });
    const panel = subscribe.closest('.panel');
    const heading = panel?.querySelector('.panel-heading');
    expect(heading?.contains(subscribe)).toBe(true);
    expect(within(heading as HTMLElement).getByRole('button', { name: 'Mês anterior' })).toBeTruthy();
    expect(screen.queryByText('A inscrição só pode ser alterada no mês atual.')).toBeNull();
    expect(screen.queryByText(/Assinar cria ou mantém/)).toBeNull();
  });

  it('envia a inscrição mensal para o endpoint próprio', async () => {
    const calls = await setup('#player-monthly');
    await screen.findByRole('button', { name: 'Assinar este mês' });
    fireEvent.click(screen.getByRole('button', { name: 'Assinar este mês' }));
    await waitFor(() => expect(calls.some(call => call.path.startsWith('/api/me/monthly?') && call.method === 'POST')).toBe(true));
  });

  it('confirma a saída mensal e avisa que cobranças existentes permanecem', async () => {
    const own = { id: 'sub-1', person_id: 'p1', name: 'Jogador', position: 1 };
    const leaveCalls = await setup('#player-monthly', { monthly: { items: [own], own_subscription: own, can_join: false, can_leave: true } });
    fireEvent.click(await screen.findByRole('button', { name: 'Sair da lista do mês' }));
    const dialog = screen.getByRole('dialog', { name: 'Sair da lista mensal?' });
    expect(within(dialog).getByText(/Cobranças mensais que já foram geradas permanecem pendentes/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirmar' }));
    await waitFor(() => expect(leaveCalls.some(call => call.path.startsWith('/api/me/monthly?') && call.method === 'DELETE')).toBe(true));
  });

  it('entra e sai da partida própria com confirmação e não ativa ações sem permissão', async () => {
    const calls = await setup('#player-games');
    fireEvent.click(await screen.findByRole('button', { name: /Abrir lista da partida de/ }));
    await screen.findByRole('table', { name: 'Participantes da partida' });
    fireEvent.click(await screen.findByRole('button', { name: 'Entrar na lista' }));
    await waitFor(() => expect(calls.some(call => call.path === '/api/me/games/g1/join' && call.method === 'POST')).toBe(true));
    fireEvent.click(await screen.findByRole('button', { name: 'Sair da lista' }));
    const dialog = screen.getByRole('dialog', { name: 'Sair da partida?' });
    expect(within(dialog).getByText(/cobrança de convidado será cancelada/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirmar' }));
    await waitFor(() => expect(calls.some(call => call.path === '/api/me/games/g1/join' && call.method === 'DELETE')).toBe(true));
  });

  it('mantém ações desativadas quando o backend fecha a inscrição/convidados', async () => {
    await setup('#player-games', { game: { ...game, can_join: false, can_add_guest: false } });
    fireEvent.click(await screen.findByRole('button', { name: /Abrir lista da partida de/ }));
    expect((await screen.findByRole('button', { name: 'Entrar na lista' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Adicionar convidado' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('mantém manager vinculado no perfil de jogador em hash direto e retorna ao manager pelo menu', async () => {
    await setup('#player-games', { manager: true });
    expect(screen.getByRole('button', { name: 'Menu do perfil de Gestor' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Partidas' }).getAttribute('aria-current')).toBe('page');
    fireEvent.click(screen.getByRole('button', { name: 'Menu do perfil de Gestor' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Painel do manager' }));
    await screen.findByRole('heading', { name: 'Próxima partida' });
    expect(location.hash).toBe('#overview');
  });

  it('mostra cobranças pendentes primeiro e usa o histórico existente de filtros', async () => {
    await setup('#player-finance', { charges: [
      { id: 'paid-new', person_id: 'p1', name: 'Pago recente', type: 'monthly', reference_date: '2026-11-01', amount_cents: 1250, status: 'paid' },
      { id: 'pending-old', person_id: 'p1', name: 'Pendente antigo', type: 'single', reference_date: '2026-10-01', amount_cents: 1000, status: 'pending' },
      { id: 'pending-new', person_id: 'p1', name: 'Pendente recente', type: 'single', reference_date: '2026-11-18', amount_cents: 1000, status: 'pending' },
    ] });
    await screen.findByRole('table', { name: 'Minhas cobranças' });
    const table = screen.getByRole('table', { name: 'Minhas cobranças' });
    const rows = [...table.querySelectorAll('tbody tr')].map(row => row.textContent ?? '');
    expect(rows[0]).toContain('Pendente recente');
    expect(rows[1]).toContain('Pendente antigo');
    expect(rows[2]).toContain('Pago recente');
  });
});
