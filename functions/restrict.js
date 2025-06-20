export default {
    async fetch(request) {
      const url = new URL(request.url);
      const path = url.pathname;
      const referer = request.headers.get('referer');
  
      if (path.endsWith('.js') || path.endsWith('.json')) {
        if (referer && referer.startsWith('https://govoet.pages.dev')) {
          return fetch(request);
        }
        return new Response('Access Denied', { status: 403 });
      }
      return fetch(request);
    }
  };