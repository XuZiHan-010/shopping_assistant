export interface MerchantMemory {
  id: string
  layer: 'FACT' | 'SUMMARY'
  category: string
  content: string
  sourceRef: { conversationId: string; messageId: string } | null
  updatedAt: string
}

export interface MerchantMemories {
  facts: MerchantMemory[]
  nextCursor: string | null
  summaries: MerchantMemory[]
}
