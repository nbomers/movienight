import { login, register, setToken } from './api.js';
import { $, togglePasswordVisibility, withBusy } from './ui.js';

const msg = $('#msg');
const show = (text, kind = 'error') => {
  msg.className = `alert alert-${kind}`;
  msg.textContent = text;
  msg.hidden = false;
};

// Invite links carry the token in the fragment (#token=…), which never
// reaches server logs. Older links used ?token=…; both work. The token is
// removed from the address bar so it does not stay in the history.
const fromHash = new URLSearchParams(window.location.hash.slice(1)).get('token');
const fromQuery = new URLSearchParams(window.location.search).get('token');
const inviteToken = fromHash || fromQuery;
if (inviteToken) {
  $('#token').value = inviteToken;
  $('#tokenField').hidden = true;
  $('#tokenOk').hidden = false;
  history.replaceState(null, '', window.location.pathname);
}

$('[data-toggle-password]').addEventListener('click', (e) => togglePasswordVisibility(e.currentTarget));

$('#registerForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  msg.hidden = true;

  const token = $('#token').value.trim();
  const username = $('#username').value.trim();
  const password = $('#password').value;

  if (!token) { $('#tokenField').hidden = false; return show('Einladungscode fehlt'); }
  if (!/^[a-zA-Z0-9_-]{3,50}$/.test(username)) return show('Benutzername: 3–50 Zeichen, nur Buchstaben, Zahlen, _ und -');
  if (password.length < 8) return show('Das Passwort braucht mindestens 8 Zeichen');
  if (password !== $('#password2').value) return show('Die Passwörter stimmen nicht überein');

  try {
    await withBusy($('#submitBtn'), async () => {
      await register(token, username, password);
      show('Account erstellt, du wirst angemeldet …', 'ok');
      const data = await login(username, password);
      setToken(data.access_token);
      window.location.replace('app.html');
    });
  } catch (ex) {
    show(ex.message);
  }
});
