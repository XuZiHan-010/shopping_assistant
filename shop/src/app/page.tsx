import Link from 'next/link'

// 没有店铺列表接口：入口只来自店铺链接。可选的默认店铺只用于本地演示的落地页。
const defaultShop = process.env.NEXT_PUBLIC_DEFAULT_SHOP_SLUG?.trim()

export default function HomePage() {
  return (
    <main className="page stack">
      <h1>Borough</h1>
      <p>请通过店铺链接进入某家店铺，例如 /店铺标识。</p>
      {defaultShop ? (
        <Link className="btn btn-primary" href={`/${defaultShop}`}>
          进入演示店铺
        </Link>
      ) : null}
    </main>
  )
}
