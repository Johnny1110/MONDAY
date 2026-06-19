import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'

// Hash history → the FastAPI server only ever serves index.html; all routing is client-side.
export const NAV = [
  { path: '/today', title: 'Today', icon: '◎' },
  { path: '/macro', title: 'Macro', icon: '◍' },
  { path: '/signals', title: 'Signals', icon: '▤' },
  { path: '/book', title: 'Book', icon: '▣' },
  { path: '/portfolio', title: 'Portfolio', icon: '▦' },
  { path: '/calibration', title: 'Calibration', icon: '◴' },
  { path: '/ledger', title: 'Ledger', icon: '▥' },
  { path: '/reports', title: 'Reports', icon: '⚑' },
  { path: '/system', title: 'System', icon: '⚙' },
  { path: '/manual', title: 'Manual', icon: '❯' },
]

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/today' },
  { path: '/today', component: () => import('./views/TodayView.vue') },
  { path: '/macro', component: () => import('./views/MacroView.vue') },
  { path: '/signals', component: () => import('./views/SignalsView.vue') },
  { path: '/book', component: () => import('./views/BookView.vue') },
  { path: '/portfolio', component: () => import('./views/PortfolioView.vue') },
  { path: '/calibration', component: () => import('./views/CalibrationView.vue') },
  { path: '/ledger', component: () => import('./views/LedgerView.vue') },
  { path: '/reports', component: () => import('./views/ReportsView.vue') },
  { path: '/system', component: () => import('./views/SystemView.vue') },
  { path: '/manual', component: () => import('./views/ManualView.vue') },
]

export const router = createRouter({ history: createWebHashHistory(), routes })
