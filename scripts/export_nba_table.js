// Run in your browser console on the visible NBA Traditional team table.
// Reads the displayed table and downloads JSON locally. No external requests or uploads.
(() => {
  const table = [...document.querySelectorAll('table')].find(t => {
    const text = t.querySelector('tr')?.innerText || '';
    return text.includes('TEAM') && text.includes('WIN%') && text.includes('PTS');
  });
  if (!table) throw new Error('Open the NBA team Traditional table and wait for it to load.');
  const filters = [...document.querySelectorAll('select')].slice(0, 3).map(s => s.value);
  if (filters.length !== 3 || filters[2] !== 'PerGame') {
    throw new Error('Select a season, season type and Per Game first.');
  }
  const names = {'TEAM': 'TEAM_NAME', 'GP': 'GP', 'W': 'W', 'L': 'L', 'WIN%': 'W_PCT',
    'MIN': 'MIN', 'PTS': 'PTS', '+/-': 'PLUS_MINUS', 'FGA': 'FGA', 'FTA': 'FTA',
    'OREB': 'OREB', 'TOV': 'TOV'};
  const rows = [...table.querySelectorAll('tr')];
  const headers = [...rows[0].children].map(c => c.innerText.trim());
  const rowSet = rows.slice(1).map(row => {
    const cells = [...row.children].map(c => c.innerText.trim());
    const id = row.querySelector('a[href*="/stats/team/"]')?.getAttribute('href')?.match(/\/stats\/team\/(\d+)/)?.[1];
    if (!id) return null;
    return [id, ...Object.keys(names).map(name => {
      const index = headers.indexOf(name);
      if (index < 0 || index >= cells.length) throw new Error('NBA table columns changed.');
      return name === 'TEAM' ? cells[index] : Number(cells[index].replaceAll(',', ''));
    })];
  }).filter(Boolean);
  const seasonTypes = {'Pre Season': 'Preseason', 'Regular Season': 'Regular Season', 'Playoffs': 'Playoffs'};
  const data = {_capture: {method: 'user export of visible browser table', source_url: location.href,
    season: filters[0], season_type: seasonTypes[filters[1]] || filters[1], per_mode: filters[2]},
    resultSets: [{name: 'LeagueDashTeamStats', headers: ['TEAM_ID', ...Object.values(names)], rowSet}]};
  const link = document.createElement('a');
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}));
  link.href = url;
  link.download = `nba-teams-${filters[0]}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
})();
