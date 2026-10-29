const signed = status => ['success', 'already', 'confirmed'].includes(status);
const statusLabel = status => ({
  success: '签到成功', already: '已签到', confirmed: '已核实完成',
  failed: '失败', uncertain: '待确认', unrecorded: '尚无记录',
  not_signed: '尚未签到',
}[status] || '尚无记录');
const statusColor = status => signed(status) ? 'success' : ['unrecorded', 'not_signed'].includes(status) ? 'default' : 'warning';
const number = value => typeof value === 'number' && Number.isFinite(value)
  ? value.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : '—';
const time = value => value ? new Date(value * 1000).toLocaleString('zh-CN', {
  timeZone: 'Asia/Shanghai', hour12: false,
}) : '尚未检查';
const connectionLabel = status => ({
  ok: '站点连通，Cookie 有效', invalid: 'Cookie 已失效', error: '检测失败，请查看提示',
}[status] || '尚未检测');

const style = '';

export { statusColor as a, connectionLabel as c, number as n, statusLabel as s, time as t };
