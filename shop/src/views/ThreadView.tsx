'use client'

import { useState } from 'react'
import { useChat } from '@/chat/ChatProvider'
import { useLocale } from '@/i18n/LocaleProvider'
import { toolDisplayName } from '@/i18n/toolNames'
import styles from './ThreadView.module.css'

export function ThreadView({ onOpenHistory }: { onOpenHistory: () => void }) {
  const { messages, busy, error, historyTruncated, resetToNew, send } = useChat()
  const { locale, t } = useLocale()
  const [expanded, setExpanded] = useState<string | null>(null)
  const lastAnswer = [...messages].reverse().find(message => message.role === 'assistant' && message.turn)?.id

  return <section className={styles.thread} aria-label={t('threadTitle')}>
    <header className={styles.header}>
      <h1>{t('threadTitle')}</h1>
      <div className={styles.actions}>
        <button type="button" onClick={onOpenHistory}>{t('history')}</button>
        <button type="button" onClick={resetToNew}>{t('newChat')}</button>
      </div>
    </header>
    {error && <p role="alert" className={styles.warning}>{error}</p>}
    {historyTruncated && <p role="status" className={styles.warning}>{t('chat.historyTruncated')}</p>}
    <ol className={styles.log} aria-live="polite">
      {messages.map(message => {
        if (message.role === 'user') return <li key={message.id} className={styles.userRow}><p className={styles.userBubble}>{message.text}</p></li>
        const calls = message.toolCalls
        const opened = expanded === message.id
        return <li key={message.id} className={styles.assistantRow}>
          <span className={styles.avatar} aria-hidden="true">✦</span>
          <div className={styles.answer}>
            <div className={styles.byline}>
              <strong>{t('clerk')}</strong>
              {calls.length > 0 && <button type="button" aria-expanded={opened} onClick={() => setExpanded(opened ? null : message.id)}>{t('stepsN', { n: calls.length })}</button>}
            </div>
            {opened && <ol className={styles.steps}>{calls.map(call => <li key={call.callId}>
              <strong>{toolDisplayName(call.toolName, locale)}</strong>
              <span>{t(`toolStatus.${call.status}`)}</span>
              {call.summary && <p>{call.summary}</p>}
            </li>)}</ol>}
            <p className={styles.answerText}>{message.text || (busy ? t('thinking') : '')}</p>
            {message.turn?.degraded && <p className={styles.warning}>{t('degraded')}{message.turn.degradedReason}</p>}
            {message.turn?.analysisSources.filter(source => source.degraded).map((source, index) => <p key={`${source.source}-${index}`} className={styles.warning}>{source.source}: {t('sourceDegraded', { reason: source.degradedReason ?? '' })}</p>)}
            {message.id === lastAnswer && message.turn?.suggestions.length ? <div className={styles.suggestions} aria-label={t('suggestedQuestions')}>
              {message.turn.suggestions.map((suggestion, index) => <button key={`${suggestion}-${index}`} type="button" disabled={busy} onClick={() => void send(suggestion)}>{suggestion}</button>)}
            </div> : null}
          </div>
        </li>
      })}
    </ol>
  </section>
}
