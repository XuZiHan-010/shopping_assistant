'use client'

import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { deleteConversation, listConversations } from '@/api/conversationsApi'
import { deleteCustomerMemory, listCustomerMemories, setCustomerMemoryPreference } from '@/api/memoryApi'
import { useChat } from '@/chat/ChatProvider'
import { translate, useLocale } from '@/i18n/LocaleProvider'
import { toolDisplayName } from '@/i18n/toolNames'
import { useShop } from '@/session/ShopContext'
import type { ConversationSummary } from '@/types/conversation'
import type { CustomerMemories } from '@/types/memory'
import styles from './ActivityDrawer.module.css'

export type ActivityTab = 'steps' | 'memory' | 'history'
interface Props { open: boolean; onClose: () => void; initialTab?: ActivityTab; triggerRef?: RefObject<HTMLElement | null>; onTabChange?: (tab: ActivityTab) => void }

export function ActivityDrawer({ open, onClose, initialTab = 'steps', triggerRef, onTabChange }: Props) {
  const { t } = useLocale()
  const { session } = useShop()
  const [selectedTab, setSelectedTab] = useState<ActivityTab | null>(null)
  const tab = selectedTab ?? initialTab
  const closeRef = useRef<HTMLButtonElement>(null)
  const rememberedFocus = useRef<HTMLElement | null>(null)
  const close = useCallback(() => { setSelectedTab(null); onClose() }, [onClose])
  useEffect(() => {
    if (!open) return
    rememberedFocus.current = triggerRef?.current ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null)
    closeRef.current?.focus()
    return () => {
      const target = rememberedFocus.current
      if (target?.isConnected) target.focus()
    }
  }, [open, triggerRef])
  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') { event.preventDefault(); close() }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, close])
  if (!open) return null
  return <div className={styles.layer}>
    <button type="button" className={styles.scrim} aria-hidden="true" onClick={close} tabIndex={-1} />
    <aside className={styles.drawer} role="dialog" aria-modal="true" aria-labelledby="activity-title">
      <header className={styles.head}><h2 id="activity-title">{t('activity')}</h2><button ref={closeRef} type="button" onClick={close} aria-label={t('close')}>×</button></header>
      <div className={styles.tabs} role="tablist" aria-label={t('activity')}>
        {(['steps', 'memory', 'history'] as const).map(name => <button key={name} type="button" role="tab" aria-selected={tab === name} onClick={() => { setSelectedTab(name); onTabChange?.(name) }}>{t(name === 'steps' ? 'tabSteps' : name === 'memory' ? 'tabMemory' : 'tabHistory')}</button>)}
      </div>
      <div className={styles.body} role="tabpanel">
        {tab === 'steps' ? <StepsPanel /> : tab === 'memory' ? <MemoryPanel key={session?.sessionId ?? 'none'} /> : <HistoryPanel key={session?.sessionId ?? 'none'} onClose={close} />}
      </div>
    </aside>
  </div>
}

function StepsPanel() {
  const { turns } = useChat()
  const { t, locale } = useLocale()
  const [selection, setSelection] = useState<number | null>(null)
  const index = selection === null ? turns.length - 1 : Math.min(selection, turns.length - 1)
  if (!turns.length) return <p className={styles.empty}>{t('noTurns')}</p>
  const record = turns[index]!
  return <div className={styles.stack}>
    <div className={styles.turnNav}>
      <button type="button" aria-label="‹" disabled={index === 0} onClick={() => setSelection(index - 1)}>‹</button>
      <span>{t('turnOf', { k: index + 1, n: turns.length })}</span>
      <button type="button" aria-label="›" disabled={index === turns.length - 1} onClick={() => setSelection(index + 1)}>›</button>
    </div>
    <p className={styles.question}>{record.question}</p>
    {record.turn.toolCalls.length ? <ol className={styles.trace}>{record.turn.toolCalls.map(call => <li key={call.callId}>
      <strong>{toolDisplayName(call.toolName, locale)}</strong><span>{t(`toolStatus.${call.status}`)}</span>
      {call.summary && <p>{call.summary}</p>}<code>{call.toolName}</code>
    </li>)}</ol> : <p className={styles.empty}>{t('noTools')}</p>}
    <div className={styles.sources}><strong>{t('sources')}</strong>
      {record.turn.analysisSources.map((source, index) => <div key={`${source.source}-${index}`}>
        <span>{source.source}</span>{source.degraded && <p className={styles.warning}>{t('sourceDegraded', { reason: source.degradedReason ?? '' })}</p>}
      </div>)}
    </div>
    {record.turn.degraded && <p className={styles.warning}>{t('degraded')}{record.turn.degradedReason}</p>}
    <p className={styles.elapsed}>{t('elapsed', { s: (record.elapsedMs / 1000).toFixed(1) })}</p>
  </div>
}

function MemoryPanel() {
  const { session, bindDemoCustomer } = useShop()
  const { t, locale } = useLocale()
  const [data, setData] = useState<CustomerMemories | null>(null)
  const [dataOwner, setDataOwner] = useState<string | null>(null)
  const [confirmOff, setConfirmOff] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    if (!session?.isBound) return
    let alive = true
    void listCustomerMemories().then(value => { if (alive) { setData(value); setDataOwner(session.sessionId) } }).catch(() => { if (alive) setError(translate(locale, 'memoryLoadFailed')) })
    return () => { alive = false }
  }, [session?.isBound, session?.sessionId, retry, locale]) // 翻译函数会随 Provider 渲染重建，语言值才是请求边界
  async function run(action: () => Promise<void>) {
    setBusy(true); setError('')
    try { await action() } catch { setError(t('memoryActionFailed')) }
    finally { setBusy(false) }
  }
  if (!session?.isBound) return <div className={styles.stack}><p>{t('memGuest')}</p><button type="button" onClick={() => void run(async () => { await bindDemoCustomer() })}>{t('bind')}</button></div>
  const visibleData = dataOwner === session.sessionId ? data : null
  return <div className={styles.stack}>
    {error && <div role="alert" className={styles.warning}>{error}<button type="button" onClick={() => setRetry(value => value + 1)}>{t('historyRetry')}</button></div>}
    {visibleData && <>
      <div className={styles.switchRow}><div><strong>{t('memToggle')}</strong><small>{t('memToggleHint')}</small></div>
        <button type="button" role="switch" aria-label={t('memToggle')} aria-checked={visibleData.memoryEnabled} disabled={busy} onClick={() => visibleData.memoryEnabled ? setConfirmOff(true) : void run(async () => { await setCustomerMemoryPreference(true); setData(current => current && { ...current, memoryEnabled: true }) })}>{visibleData.memoryEnabled ? '●' : '○'}</button>
      </div>
      {confirmOff && <div className={styles.confirm} role="group" aria-label={t('memConfirmOff', { n: visibleData.items.length })}>
        <p>{t('memConfirmOff', { n: visibleData.items.length })}</p>
        <button type="button" onClick={() => setConfirmOff(false)}>{t('memoryCancel')}</button>
        <button type="button" disabled={busy} onClick={() => void run(async () => { await setCustomerMemoryPreference(false); setData(current => current && { ...current, memoryEnabled: false, items: [] }); setConfirmOff(false) })}>{t('memoryConfirmAction')}</button>
      </div>}
      {!visibleData.memoryEnabled ? <p>{t('memOff')}</p> : visibleData.items.length === 0 ? <p>{t('memEmpty')}</p> : <ul className={styles.list}>{visibleData.items.map(item => <li key={item.id} className={styles.item}>
        <strong>{item.category} · {item.key}</strong><p>{item.value}</p>
        <small>{new Intl.DateTimeFormat(locale).format(new Date(item.expiresAt))}</small>
        <button type="button" disabled={busy} aria-label={`${t('delete')}：${item.key}`} onClick={() => void run(async () => { await deleteCustomerMemory(item.id); setData(current => current && { ...current, items: current.items.filter(memory => memory.id !== item.id) }) })}>{t('delete')}</button>
      </li>)}</ul>}
      {visibleData.nextCursor && <button type="button" disabled={busy} onClick={() => void run(async () => { const page = await listCustomerMemories(visibleData.nextCursor ?? undefined); setData(current => current && { ...page, items: [...current.items, ...page.items] }) })}>{t('historyLoadMore')}</button>}
    </>}
  </div>
}

function HistoryPanel({ onClose }: { onClose: () => void }) {
  const { conversationId, messages, directoryVersion, busy, resetToNew, openConversation, onDeleted, setError } = useChat()
  const { t, locale } = useLocale()
  const [items, setItems] = useState<ConversationSummary[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [phase, setPhase] = useState<'loading' | 'ready' | 'failed'>('loading')
  const [retry, setRetry] = useState(0)
  const [removing, setRemoving] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    void listConversations().then(page => { if (alive) { setItems(page.items); setNextCursor(page.nextCursor); setPhase('ready') } }).catch(() => { if (alive) setPhase('failed') })
    return () => { alive = false }
  }, [directoryVersion, retry])
  async function remove(id: string) {
    setRemoving(id)
    try { await deleteConversation(id); setItems(current => current.filter(item => item.id !== id)); onDeleted(id) }
    catch { setError(t('historyDeleteFailed')) }
    finally { setRemoving(null) }
  }
  return <div className={styles.stack}>
    <button type="button" disabled={busy} onClick={() => { resetToNew(); onClose() }}>{t('newChat')}</button>
    {phase === 'failed' ? <div role="alert">{t('historyLoadFailed')} <button type="button" onClick={() => { setPhase('loading'); setRetry(value => value + 1) }}>{t('historyRetry')}</button></div> : null}
    {conversationId && !items.some(item => item.id === conversationId) && <div className={styles.item} aria-current="true"><strong>{t('current')}</strong><p>{messages.find(message => message.role === 'user')?.text}</p></div>}
    {phase === 'ready' && !items.length && !conversationId && <p className={styles.empty}>{t('historyEmpty')}</p>}
    <ul className={styles.list}>{items.map(item => <li key={item.id} className={styles.item}>
      <button type="button" aria-current={item.id === conversationId ? 'true' : undefined} disabled={busy} onClick={() => { void openConversation(item.id).then(onClose) }}>{item.title}</button>
      <small>{new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(new Date(item.updatedAt))}</small>
      <button type="button" aria-label={`${t('delete')}：${item.title}`} disabled={busy || removing === item.id} onClick={() => void remove(item.id)}>{t('delete')}</button>
    </li>)}</ul>
    {nextCursor && <button type="button" onClick={() => void listConversations(nextCursor).then(page => { setItems(current => [...current, ...page.items.filter(item => !current.some(old => old.id === item.id))]); setNextCursor(page.nextCursor) }).catch(() => setError(t('historyLoadFailed')))}>{t('historyLoadMore')}</button>}
  </div>
}
