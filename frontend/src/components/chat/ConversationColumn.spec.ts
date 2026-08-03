import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ChatComposer from './ChatComposer.vue'
import ConversationColumn from './ConversationColumn.vue'

describe('ConversationColumn', () => {
  it('组合独立的 ChatComposer 与可滚动消息区域', () => {
    const wrapper = mount(ConversationColumn)

    expect(wrapper.findComponent(ChatComposer).exists()).toBe(true)
    expect(wrapper.find('[data-testid="chat-list"]').exists()).toBe(true)
  })
})
