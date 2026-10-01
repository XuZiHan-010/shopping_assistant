export interface CustomerMemory {
  id: string
  shopSlug: string
  category: string
  key: string
  value: string
  lastConfirmedAt: string
  expiresAt: string
}

export interface CustomerMemories {
  memoryEnabled: boolean
  items: CustomerMemory[]
  nextCursor: string | null
}
