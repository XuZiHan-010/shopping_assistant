import type { Metadata } from 'next'
import { Fraunces, Instrument_Sans } from 'next/font/google'
import { serverLocale } from '../i18n/serverLocale'
import { LocaleProvider } from '../i18n/LocaleProvider'
import { bootScript } from '../preferences/bootScript'
import type { ReactNode } from 'react'
import './globals.css'

const fraunces = Fraunces({ subsets: ['latin'], display: 'swap', variable: '--font-fraunces' })
const instrument = Instrument_Sans({ subsets: ['latin'], display: 'swap', variable: '--font-instrument' })
// 中文字体不走 next/font：它会在构建镜像时把每个字重的一百多个分片逐个下载下来，
// 任何一次网络抖动都会让整个构建失败（2026-10-10 顾客端部署因此失败，202 个字体文件取不到）。
// 改为浏览器运行时加载；取不到时回退到 shop-tokens.css 里列出的系统字体。
const CJK_FONTS_HREF =
  'https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&family=Noto+Serif+SC:wght@600;700&display=swap'

export const metadata: Metadata = {
  title: 'Borough 店铺',
  description: 'Borough 顾客端：智能助手、购物与售后（演示环境）。',
  icons: { icon: '/borough-logo.svg' },
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const lang = await serverLocale()
  return (
    <html lang={lang} suppressHydrationWarning className={`${fraunces.variable} ${instrument.variable}`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: bootScript }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link rel="stylesheet" href={CJK_FONTS_HREF} />
      </head>
      <body><LocaleProvider initialLocale={lang}>{children}</LocaleProvider></body>
    </html>
  )
}
