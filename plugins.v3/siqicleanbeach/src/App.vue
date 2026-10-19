<template>
  <v-app><v-main><component :is="active === 'config' ? Config : Page" :api="api" plugin-id="SiQiCleanBeach" @switch="active = $event" @close="active = 'page'" /></v-main></v-app>
</template>
<script setup>
import { ref } from 'vue'
import Config from './components/Config.vue'
import Page from './components/Page.vue'
const active = ref('page')
async function request(path, method = 'GET', payload) {
  const response = await fetch(`/api/v1/${path}`, { method, headers: { 'Content-Type': 'application/json' }, ...(payload === undefined ? {} : { body: JSON.stringify(payload) }) })
  if (!response.ok) throw new Error('request failed')
  return response.json()
}
const api = { get: path => request(path), post: (path, payload) => request(path, 'POST', payload) }
</script>
