import type { Metadata } from 'next'
import { Fraunces, Instrument_Sans, Noto_Serif_SC, Noto_Sans_SC } from 'next/font/google'
import { serverLocale } from '../i18n/serverLocale'
import { LocaleProvider } from '../i18n/LocaleProvider'
import { bootScript } from '../preferences/bootScript'
import type { ReactNode } from 'react'
import './globals.css'

const fraunces = Fraunces({ subsets: ['latin'], display: 'swap', variable: '--font-fraunces' })
const instrument = Instrument_Sans({ subsets: ['latin'], display: 'swap', variable: '--font-instrument' })
const serif = Noto_Serif_SC({ weight: ['600', '700'], preload: false, display: 'swap', variable: '--font-noto-serif' })
const sans = Noto_Sans_SC({ weight: ['400', '500', '700'], preload: false, display: 'swap', variable: '--font-noto-sans' })

export const metadata: Metadata = {
  title: 'Borough 店铺',
  description: 'Borough 顾客端：智能助手、购物与售后（演示环境）。',
  icons: { icon: '/borough-logo.svg' },
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const lang = await serverLocale()
  return (
    <html lang={lang} suppressHydrationWarning className={`${fraunces.variable} ${instrument.variable} ${serif.variable} ${sans.variable}`}>
      <head><script dangerouslySetInnerHTML={{ __html: bootScript }} /></head>
      <body><LocaleProvider initialLocale={lang}>{children}</LocaleProvider></body>
    </html>
  )
}
