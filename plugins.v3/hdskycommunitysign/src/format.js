export const signed = status => ['success', 'already', 'confirmed'].includes(status)
export const statusLabel = status => ({
  success: '签到成功', already: '已签到', confirmed: '已核实完成',
  failed: '失败', uncertain: '待确认', unrecorded: '尚无记录',
}[status] || '尚无记录')
export const statusColor = status => signed(status) ? 'success' : status === 'unrecorded' ? 'default' : 'warning'
export const number = value => typeof value === 'number' && Number.isFinite(value)
  ? value.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : '—'
export const time = value => value ? new Date(value * 1000).toLocaleString('zh-CN', {
  timeZone: 'Asia/Shanghai', hour12: false,
}) : '尚未检查'
