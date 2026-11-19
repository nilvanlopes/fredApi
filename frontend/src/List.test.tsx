import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { DataCards, DataTable, filterAndSort, type Column } from './List';

interface Item { id: string; name: string; amount: number; position: number; status: string; timestamp: string; day: string }
const items: Item[] = [
  { id: 'a', name: 'Érica', amount: 1250, position: 10, status: 'waiting', timestamp: '2026-11-12T01:30:00Z', day: '2026-11-11' },
  { id: 'b', name: 'ábaco', amount: 710, position: 2, status: 'main', timestamp: '2026-11-11T19:30:00-03:00', day: '2026-11-04' },
  { id: 'c', name: 'Ana', amount: 100000, position: 1, status: 'main', timestamp: '2026-11-11T22:00:00Z', day: '2026-10-28' },
];
const columns: Column<Item>[] = [
  { id: 'name', label: 'Jogador', value: x => x.name },
  { id: 'amount', label: 'Valor', kind: 'money', value: x => x.amount },
  { id: 'position', label: 'Posição', kind: 'number', value: x => x.position },
  { id: 'status', label: 'Lista', kind: 'select', options: [{ value: 'main', label: 'Principal' }, { value: 'waiting', label: 'Espera' }], value: x => x.status },
  { id: 'timestamp', label: 'Início', kind: 'datetime', value: x => x.timestamp },
  { id: 'day', label: 'Data', kind: 'date', value: x => x.day },
];
const ids = (rows: Item[]) => rows.map(x => x.id);

describe('comparação e filtros das listas', () => {
  it('ordena nomes em pt-BR sem distinguir acentos/caixa', () => {
    expect(ids(filterAndSort(items, columns, {}, { id: 'name', direction: 'asc' }))).toEqual(['b', 'c', 'a']);
    expect(ids(filterAndSort(items, columns, { name: { value: 'ERICA' } }))).toEqual(['a']);
  });
  it('compara posições numericamente e não altera a ordem original da API', () => {
    const original = ids(items);
    expect(ids(filterAndSort(items, columns, {}, { id: 'position', direction: 'asc' }))).toEqual(['c', 'b', 'a']);
    expect(ids(items)).toEqual(original);
  });
  it('ordena centavos numericamente e filtra valores em reais com arredondamento', () => {
    expect(ids(filterAndSort(items, columns, {}, { id: 'amount', direction: 'asc' }))).toEqual(['b', 'a', 'c']);
    expect(ids(filterAndSort(items, columns, { amount: { min: '7,10', max: '7.10' } }))).toEqual(['b']);
    expect(ids(filterAndSort(items, columns, { amount: { min: '12.50', max: '12.50' } }))).toEqual(['a']);
  });
  it('combina filtros de texto, lista, intervalo de valor e data', () => {
    expect(ids(filterAndSort(items, columns, { name: { value: 'a' }, status: { value: 'main' }, amount: { max: '10' }, day: { min: '2026-11-01', max: '2026-11-10' } }))).toEqual(['b']);
    expect(filterAndSort(items, columns, { amount: { min: '20', max: '10' } })).toEqual([]);
  });
  it('filtra horários pelo fuso de São Paulo e ordena pelo timestamp real', () => {
    expect(ids(filterAndSort(items, columns, { timestamp: { min: '2026-11-11T22:00', max: '2026-11-11T23:00' } }))).toEqual(['a']);
    expect(ids(filterAndSort(items, columns, {}, { id: 'timestamp', direction: 'asc' }))).toEqual(['c', 'b', 'a']);
    expect(ids(filterAndSort(items, columns, { day: { min: '2026-11-04', max: '2026-11-04' } }))).toEqual(['b']);
  });
});

describe('cabeçalhos interativos', () => {
  it('expõe a tabela em região focável sem retirar acesso aos filtros e ações', () => {
    render(<DataTable name="Participantes" items={items} columns={columns} rowKey={x => x.id} actions={item => <button type="button">Ver {item.name}</button>}/>);
    const region = screen.getByRole('region', { name: 'Tabela Participantes, role horizontalmente para ver todas as colunas' });
    expect(region.getAttribute('tabindex')).toBe('0');
    expect(within(region).getByRole('table', { name: 'Participantes' })).toBeTruthy();

    const heading = within(region).getByRole('button', { name: 'Jogador' });
    fireEvent.click(heading);
    expect(within(region).getByRole('searchbox', { name: 'Filtrar Jogador — Participantes' })).toBeTruthy();
    expect(within(region).getByRole('button', { name: 'Ver Ana' })).toBeTruthy();
  });

  it('oferece sort asc/desc/original com aria-sort e reset completo', () => {
    render(<DataTable name="Participantes" items={items} columns={columns} rowKey={x => x.id}/>);
    const header = screen.getByRole('columnheader', { name: /Jogador/ });
    expect(header.getAttribute('aria-sort')).toBe('none');
    fireEvent.click(screen.getByRole('button', { name: 'Ordenar Jogador — Participantes: crescente' }));
    expect(header.getAttribute('aria-sort')).toBe('ascending');
    fireEvent.click(screen.getByRole('button', { name: 'Ordenar Jogador — Participantes: decrescente' }));
    expect(header.getAttribute('aria-sort')).toBe('descending');
    fireEvent.click(screen.getByRole('button', { name: 'Lista' }));
    fireEvent.change(screen.getByLabelText('Filtrar Lista — Participantes'), { target: { value: 'waiting' } });
    expect(screen.getAllByRole('row')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'Limpar filtros e ordenação — Participantes' }));
    expect(header.getAttribute('aria-sort')).toBe('none');
    expect(screen.getAllByRole('row')).toHaveLength(4);
  });
  it('mantém filtro e ordenação quando uma recarga entrega novos dados', () => {
    const view = render(<DataTable name="Participantes" items={items} columns={columns} rowKey={x => x.id}/>);
    fireEvent.click(screen.getByRole('button', { name: 'Lista' }));
    fireEvent.change(screen.getByLabelText('Filtrar Lista — Participantes'), { target: { value: 'main' } });
    fireEvent.click(screen.getByRole('button', { name: 'Ordenar Posição — Participantes: crescente' }));
    view.rerender(<DataTable name="Participantes" items={[...items, { ...items[1], id: 'd', name: 'Daniel', position: 20 }]} columns={columns} rowKey={x => x.id}/>);
    expect((screen.getByLabelText('Filtrar Lista — Participantes') as HTMLSelectElement).value).toBe('main');
    expect(screen.getByRole('columnheader', { name: /Posição/ }).getAttribute('aria-sort')).toBe('ascending');
    const body = screen.getByRole('table').querySelector('tbody')!;
    expect(within(body).getAllByRole('row').map(row => row.querySelector('[data-label="Jogador"]')?.textContent)).toEqual(['Ana', 'ábaco', 'Daniel']);
  });
  it('distingue lista vazia de resultado filtrado vazio', () => {
    render(<DataTable name="Jogadores" items={items} columns={columns} rowKey={x => x.id} emptyTitle="Nenhum jogador cadastrado"/>);
    fireEvent.click(screen.getByRole('button', { name: 'Jogador' }));
    fireEvent.change(screen.getByLabelText('Filtrar Jogador — Jogadores'), { target: { value: 'não existe' } });
    expect(screen.getByText('Nenhum resultado para estes filtros')).toBeTruthy();
    expect(screen.queryByText('Nenhum jogador cadastrado')).toBeNull();
  });
  it('só oferece datas e horários existentes, em ordem e no fuso de Brasília', () => {
    render(<DataTable name="Partidas" items={items} columns={columns} rowKey={x => x.id}/>);
    fireEvent.click(screen.getByRole('button', { name: 'Data' }));
    const from = screen.getByRole('combobox', { name: 'Filtrar Data — Partidas, de' });
    const to = screen.getByRole('combobox', { name: 'Filtrar Data — Partidas, até' });
    expect(within(from).getAllByRole<HTMLOptionElement>('option').map(option => option.value)).toEqual(['', '2026-10-28', '2026-11-04', '2026-11-11']);
    fireEvent.change(from, { target: { value: '2026-11-04' } });
    fireEvent.change(to, { target: { value: '2026-11-04' } });
    expect(screen.getAllByRole('row')).toHaveLength(2);
    expect(screen.getByText('ábaco')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Limpar filtros e ordenação — Partidas' }));
    fireEvent.click(screen.getByRole('button', { name: 'Início' }));
    const start = screen.getByRole('combobox', { name: 'Filtrar Início — Partidas, de' });
    const evening = within(start).getByRole<HTMLOptionElement>('option', { name: /11\/11\/2026.*22:30/ });
    fireEvent.change(start, { target: { value: evening.value } });
    expect(screen.getAllByRole('row')).toHaveLength(2);
    expect(screen.getByText('Érica')).toBeTruthy();
  });
  it('retira escolhas de data que deixaram de existir e esconde o campo sem datas', () => {
    const dateColumn = columns.filter(column => column.id === 'day');
    const view = render(<DataTable name="Partidas" items={items} columns={dateColumn} rowKey={x => x.id}/>);
    fireEvent.click(screen.getByRole('button', { name: 'Data' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Filtrar Data — Partidas, de' }), { target: { value: '2026-11-11' } });
    view.rerender(<DataTable name="Partidas" items={items.slice(1)} columns={dateColumn} rowKey={x => x.id}/>);
    expect(screen.getByRole<HTMLSelectElement>('combobox', { name: 'Filtrar Data — Partidas, de' }).value).toBe('');
    expect(screen.getAllByRole('row')).toHaveLength(3);
    view.rerender(<DataTable name="Partidas" items={[]} columns={dateColumn} rowKey={x => x.id}/>);
    expect(screen.queryByRole('combobox', { name: /Filtrar Data/ })).toBeNull();
  });
  it('abre filtros pelo texto do cabeçalho e mantém o botão de ordenar separado', () => {
    const compactColumns: Column<Item>[] = [
      { ...columns[0], filter: 'on-click' },
      { ...columns[2], filter: 'hidden' },
      { ...columns[3], filter: 'on-click' },
    ];
    render(<DataTable name="Assinantes" items={items} columns={compactColumns} rowKey={x => x.id} showSummary={false}/>);
    expect(screen.queryByRole('status')).toBeNull();
    expect(screen.queryByRole('spinbutton', { name: /Filtrar Posição/ })).toBeNull();
    expect(screen.queryByRole('searchbox', { name: 'Filtrar Jogador — Assinantes' })).toBeNull();
    expect(screen.queryByRole('combobox', { name: 'Filtrar Lista — Assinantes' })).toBeNull();

    const heading = screen.getByRole('button', { name: 'Jogador' });
    fireEvent.click(heading);
    expect(heading.getAttribute('aria-expanded')).toBe('true');
    fireEvent.change(screen.getByRole('searchbox', { name: 'Filtrar Jogador — Assinantes' }), { target: { value: 'ERICA' } });
    expect(screen.getAllByRole('row')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'Ordenar Jogador — Assinantes: crescente' }));
    expect(screen.getByRole('columnheader', { name: /Jogador/ }).getAttribute('aria-sort')).toBe('ascending');
    fireEvent.click(heading);
    expect(screen.queryByRole('searchbox', { name: 'Filtrar Jogador — Assinantes' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Lista' }));
    expect(screen.getByRole('combobox', { name: 'Filtrar Lista — Assinantes' })).toBeTruthy();
  });
  it('cards têm controles equivalentes e aplicam limite após filtrar e ordenar', () => {
    render(<DataCards name="Devedores" items={items} columns={columns.slice(0, 2)} limit={1} scope="filtros sobre todos os registros">{rows => <ul>{rows.map(row => <li key={row.id}>{row.name}</li>)}</ul>}</DataCards>);
    fireEvent.click(screen.getByRole('button', { name: 'Ordenar Valor — Devedores: crescente' }));
    expect(screen.getAllByRole('listitem').map(item => item.textContent)).toEqual(['ábaco']);
    fireEvent.change(screen.getByLabelText('Filtrar Jogador — Devedores'), { target: { value: 'ERICA' } });
    expect(screen.getAllByRole('listitem').map(item => item.textContent)).toEqual(['Érica']);
    expect(screen.getByRole('group', { name: 'Filtros e ordenação — Devedores' })).toBeTruthy();
  });
  it('mostra a contagem depois dos cards e oferece reset junto dos filtros só quando necessário', () => {
    render(<DataCards name="Dívidas por jogador" items={items} columns={columns.slice(0, 2)} defaultSort={{ id: 'amount', direction: 'desc' }}>
      {rows => <ul>{rows.map(row => <li key={row.id}>{row.name}</li>)}</ul>}
    </DataCards>);
    const toolbar = within(screen.getByRole('group', { name: 'Filtros e ordenação — Dívidas por jogador' }));
    const reset = { name: 'Limpar filtros e ordenação — Dívidas por jogador' };
    const summary = screen.getByRole('status');
    expect(summary.textContent?.trim()).toBe('3 de 3 registros');
    expect(screen.getByRole('list').nextElementSibling?.contains(summary)).toBe(true);
    expect(toolbar.queryByRole('button', reset)).toBeNull();
    expect(screen.getAllByRole('listitem').map(item => item.textContent)).toEqual(['Ana', 'Érica', 'ábaco']);

    const search = toolbar.getByRole('searchbox', { name: 'Filtrar Jogador — Dívidas por jogador' });
    fireEvent.change(search, { target: { value: 'ERICA' } });
    expect(toolbar.getByRole('button', reset).textContent).toBe('');
    fireEvent.change(search, { target: { value: '' } });
    expect(toolbar.queryByRole('button', reset)).toBeNull();

    fireEvent.click(toolbar.getByRole('button', { name: 'Ordenar Valor — Dívidas por jogador: ordem original' }));
    expect(toolbar.getByRole('button', reset)).toBeTruthy();
    fireEvent.change(search, { target: { value: 'sem resultados' } });
    expect(summary.textContent).toContain('0 de 3 registros');
    fireEvent.click(toolbar.getByRole('button', reset));
    expect(screen.getAllByRole('listitem').map(item => item.textContent)).toEqual(['Ana', 'Érica', 'ábaco']);
    expect(toolbar.queryByRole('button', reset)).toBeNull();
  });
});
