/** Hash routes: `#/` is the network map, `#/hospital/<id>` the 3D view of one hospital. */
import { useEffect, useState } from 'react';

export type Route = { page: 'network' } | { page: 'hospital'; hospitalId: string };

export function parseRoute(hash: string): Route {
  const m = /^#\/hospital\/([A-Za-z0-9_-]+)\/?$/.exec(hash);
  if (m?.[1]) return { page: 'hospital', hospitalId: m[1] };
  return { page: 'network' };
}

export function routeHash(route: Route): string {
  return route.page === 'hospital' ? `#/hospital/${route.hospitalId}` : '#/';
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute(location.hash));
  useEffect(() => {
    const on = () => { setRoute(parseRoute(location.hash)); };
    window.addEventListener('hashchange', on);
    return () => { window.removeEventListener('hashchange', on); };
  }, []);
  return route;
}

export function go(route: Route): void {
  location.hash = routeHash(route);
}

/** `?freeze=1` holds sim time (screenshot tests). */
export function isFreeze(search: string): boolean {
  return new URLSearchParams(search).get('freeze') === '1';
}
