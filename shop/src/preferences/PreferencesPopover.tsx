'use client'
import { useEffect, useRef, useState } from 'react'
import { useLocale } from '../i18n/LocaleProvider'
import { loadPreferences, savePreferences, type Preferences, type Theme, type TextSize } from './preferences'
export function PreferencesPopover() {
  const { locale, t, setLocale } = useLocale()
  const [open, setOpen] = useState(false)
  const [prefs, setPrefs] = useState<Preferences>({ theme: 'system', size: 'md' })
  const trigger = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    panel.current?.querySelector<HTMLButtonElement>('button')?.focus()
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setOpen(false); trigger.current?.focus() }
      if (event.key === 'Tab') {
        const controls = panel.current?.querySelectorAll<HTMLButtonElement>('button')
        if (!controls?.length) return
        const first = controls[0]!, last = controls[controls.length - 1]!
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
      }
    }
    document.addEventListener('keydown', close)
    return () => document.removeEventListener('keydown', close)
  }, [open])
  function update(next: Preferences) { setPrefs(next); savePreferences(next) }
  return <div className="preferences">
    <button ref={trigger} className="preferences-trigger" aria-label={t('prefs.title')} aria-expanded={open} aria-controls="shop-preferences" onClick={() => { setPrefs(loadPreferences()); setOpen(!open) }}>⚙</button>
    {open && <><button className="preferences-backdrop" aria-label={t('close')} tabIndex={-1} onClick={() => { setOpen(false); trigger.current?.focus() }} />
      <div ref={panel} id="shop-preferences" className="preferences-popover" role="dialog" aria-modal="true" aria-label={t('prefs.title')}>
        <header><strong>{t('prefs.title')}</strong><button aria-label={t('close')} onClick={() => { setOpen(false); trigger.current?.focus() }}>×</button></header>
        <fieldset><legend>{t('prefs.theme')}</legend><p>{t('prefs.themeHint')}</p><div>{(['system', 'light', 'dark'] as Theme[]).map(theme => <button key={theme} aria-pressed={prefs.theme === theme} onClick={() => update({ ...prefs, theme })}>{t(`prefs.${theme}`)}</button>)}</div></fieldset>
        <fieldset><legend>{t('prefs.lang')}</legend><p>{t('prefs.langHint')}</p><div>{(['zh-CN', 'en-US'] as const).map(lang => <button key={lang} lang={lang} aria-pressed={locale === lang} onClick={() => setLocale(lang)}>{lang === 'zh-CN' ? '中文' : 'English'}</button>)}</div></fieldset>
        <fieldset><legend>{t('prefs.size')}</legend><p>{t('prefs.sizeHint')}</p><div>{(['sm', 'md', 'lg'] as TextSize[]).map(size => <button key={size} aria-pressed={prefs.size === size} onClick={() => update({ ...prefs, size })}>{t(`prefs.${size}`)}</button>)}</div></fieldset>
      </div></>}
  </div>
}
