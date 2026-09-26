import Keycloak from 'keycloak-js';

const mode=import.meta.env.VITE_AUTH_MODE||'dev';
function keycloakUrl(){
  if (import.meta.env.DEV) return '/auth';
  const configured=import.meta.env.VITE_KEYCLOAK_URL;
  const configuredHost=configured ? new URL(configured).hostname : '';
  const localHost=configuredHost==='localhost'||configuredHost==='127.0.0.1';
  const forwardingDomain=import.meta.env.VITE_CODESPACES_DOMAIN;
  const hostname=window.location.hostname;
  const suffix=forwardingDomain ? `.${forwardingDomain}` : '';
  if((!configured||localHost)&&suffix&&hostname.endsWith(suffix)){
    const workspace=hostname.slice(0,-suffix.length).replace(/-\d+$/,'');
    if(workspace!==hostname.slice(0,-suffix.length)){
      return `${window.location.protocol}//${workspace}-8080${suffix}`;
    }
  }
  return configured||'http://localhost:8080';
}

export const keycloak=mode==='keycloak' ? new Keycloak({
  url: keycloakUrl(),
  realm: import.meta.env.VITE_KEYCLOAK_REALM||'enterprise',
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID||'enterprise-web'
}) : null;

export async function initAuth(){
  if(!keycloak) return;
  await keycloak.init({onLoad:'login-required',checkLoginIframe:false});
}

export async function authHeaders():Promise<Record<string,string>>{
  if (!keycloak) return {};

  try {
    await keycloak.updateToken(30);
  } catch {
    void keycloak.login();
    throw new Error('Session expirée. Reconnexion en cours.');
  }

  return keycloak.token ? {Authorization:`Bearer ${keycloak.token}`} : {};
}
