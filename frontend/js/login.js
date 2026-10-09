import { getToken, login, setToken } from './api.js';
import { $, togglePasswordVisibility, withBusy } from './ui.js';

if (getToken()) window.location.replace('app.html');

const error = $('#error');
$('[data-toggle-password]').addEventListener('click', (e) => togglePasswordVisibility(e.currentTarget));

$('#loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  error.hidden = true;
  const username = $('#username').value.trim();
  const password = $('#password').value;
  if (!username || !password) {
    error.textContent = 'Bitte Benutzername und Passwort eingeben';
    error.hidden = false;
    return;
  }
  try {
    await withBusy($('#submitBtn'), async () => {
      const data = await login(username, password);
      setToken(data.access_token);
      window.location.replace('app.html');
    });
  } catch (ex) {
    error.textContent = ex.message;
    error.hidden = false;
    $('#password').select();
  }
});
