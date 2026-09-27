import type { Metadata } from 'next'
import { headers } from 'next/headers'
import type { ReactNode } from 'react'
import './globals.css'

export const metadata: Metadata = {
  title: 'Borough 店铺',
  description: 'Borough 顾客端：店铺内导购、购物与售后（演示环境）。',
  icons: { icon: '/borough-logo.svg' },
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const acceptLanguage = (await headers()).get('accept-language')?.trim().toLowerCase()
  const lang = acceptLanguage?.startsWith('en') ? 'en-US' : 'zh-CN'
  return (
    <html lang={lang}>
      <body>{children}</body>
    </html>
  )
}
