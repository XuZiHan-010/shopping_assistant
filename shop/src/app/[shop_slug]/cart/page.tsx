import { redirect } from 'next/navigation'

export default async function CartPage({ params }: { params: Promise<{ shop_slug: string }> }) {
  const { shop_slug } = await params
  redirect(`/${shop_slug}?panel=cart`)
}
