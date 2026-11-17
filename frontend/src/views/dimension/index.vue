<template>
  <section class="page" data-module="dimension">
    <header class="page-head">
      <div>
        <h2>维度管理管理</h2>
        <p class="page-desc">维护分析维度，围绕维度编号、维度名称、维度类型、关联数据集做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">登记分析维度</button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">导出维度管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无维度管理数据，可先登记分析维度</td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记分析维度</h3>
        <label v-for="field in columns" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <!-- 维度层级合并：来源明细 → 批次合并结果 → 单一维度层级索引 → 下游汇总核对 -->
    <section class="merge-section" data-testid="merge-section">
      <header class="page-head">
        <div>
          <h3>维度层级合并</h3>
          <p class="page-desc">
            组织调整后两个部门同时批量导入成员归属，既有层级索引为同一成员保留了两条父路径。
            在这里批量选择导入记录生成维度批次合并结果，按父子路径合并重复维度成员，重建单一维度层级索引。
          </p>
        </div>
      </header>

      <div class="merge-grid">
        <article class="merge-card">
          <h4>① 来源明细（部门维度批量导入记录）</h4>
          <div class="merge-toolbar">
            <label class="filter-item">
              <span>合并策略</span>
              <select v-model="mergeStrategy" data-testid="merge-strategy">
                <option v-for="item in strategies" :key="item" :value="item">{{ item }}</option>
              </select>
            </label>
            <button
              class="btn primary"
              data-testid="run-merge"
              type="button"
              :disabled="merging || !selectedImportIds.length"
              @click="runMerge"
            >
              {{ merging ? '合并中…' : `生成维度批次合并结果（已选 ${selectedImportIds.length} 条）` }}
            </button>
          </div>
          <table class="data-table">
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    data-testid="select-all-imports"
                    :checked="allSelected"
                    @change="toggleSelectAll"
                  />
                </th>
                <th v-for="column in importColumns" :key="column">{{ column }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in importRows" :key="String(row.id)" :data-testid="`import-row-${row.id}`">
                <td>
                  <input
                    v-model="selectedImportIds"
                    type="checkbox"
                    :value="Number(row.id)"
                    :data-testid="`select-import-${row.id}`"
                  />
                </td>
                <td v-for="column in importColumns" :key="column">{{ row[column] || '—' }}</td>
              </tr>
              <tr v-if="!importRows.length">
                <td :colspan="importColumns.length + 1" class="empty-state">暂无来源明细，可先在下方批量导入</td>
              </tr>
            </tbody>
          </table>
          <form class="import-form" @submit.prevent="submitImport">
            <label v-for="field in importFormFields" :key="field" class="filter-item">
              <span>{{ field }}</span>
              <input v-model="importForm[field]" :data-testid="`import-${field}`" :placeholder="`填写${field}`" />
            </label>
            <button class="btn" data-testid="submit-import" type="submit" :disabled="importing">
              {{ importing ? '导入中…' : '批量导入成员归属' }}
            </button>
          </form>
          <ul v-if="importResults.length" class="result-list" data-testid="import-results">
            <li v-for="item in importResults" :key="`imp-${item.序号}`" :class="item.ok ? 'ok-text' : 'error-text'">
              第{{ item.序号 }}条：{{ item.message }}
            </li>
          </ul>
        </article>

        <article class="merge-card">
          <h4>② 维度批次合并结果</h4>
          <table class="data-table">
            <thead>
              <tr>
                <th v-for="column in mergeColumns" :key="column">{{ column }}</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in mergeRows" :key="String(row.id)" :data-testid="`merge-row-${row.id}`">
                <td v-for="column in mergeColumns" :key="column">{{ row[column] ?? '—' }}</td>
                <td>
                  <button class="link" type="button" :data-testid="`merge-detail-${row.id}`" @click="openMergeDetail(Number(row.id))">
                    查看合并过程
                  </button>
                </td>
              </tr>
              <tr v-if="!mergeRows.length">
                <td :colspan="mergeColumns.length + 1" class="empty-state">暂无维度批次合并结果，请先在左侧选择来源明细</td>
              </tr>
            </tbody>
          </table>
          <p v-if="mergeMessage" class="merge-message" data-testid="merge-message">{{ mergeMessage }}</p>
          <ul v-if="mergeRecordResults.length" class="result-list" data-testid="merge-record-results">
            <li v-for="item in mergeRecordResults" :key="`rec-${item.import_id}`" :class="item.ok ? 'ok-text' : 'error-text'">
              导入记录 #{{ item.import_id }}：{{ item.ok ? '成功' : '失败' }}（{{ item.message }}）
            </li>
          </ul>

          <div v-if="mergeDetail" class="merge-detail" data-testid="merge-detail">
            <h5>合并过程：{{ mergeDetail.合并批次 }}（{{ mergeDetail.合并策略 }} → 索引版本 {{ mergeDetail.索引版本 }}）</h5>
            <p class="page-desc">
              来源输入：{{ mergeDetailSourceText }}
            </p>
            <table class="data-table">
              <thead>
                <tr>
                  <th>成员编码</th>
                  <th>成员名称</th>
                  <th>候选父路径</th>
                  <th>选定父路径</th>
                  <th>是否冲突</th>
                  <th>取舍说明</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in mergeDetail.成员合并明细 || []" :key="String(item.成员编码)">
                  <td>{{ item.成员编码 }}</td>
                  <td>{{ item.成员名称 }}</td>
                  <td>
                    <span v-for="candidate in item.候选父路径" :key="`${item.成员编码}-${candidate.父路径}`" class="candidate-path">
                      {{ candidate.父路径 }}（{{ candidate.来源部门 }}·{{ candidate.来源类型 }}）
                    </span>
                  </td>
                  <td><strong>{{ item.选定父路径 }}</strong></td>
                  <td>{{ item.是否冲突 ? '冲突已合并' : '无冲突' }}</td>
                  <td>{{ item.取舍说明 }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>
      </div>

      <div class="merge-grid">
        <article class="merge-card">
          <h4>③ 单一维度层级索引（交付数据，当前版本 {{ hierarchyVersion || '—' }}）</h4>
          <table class="data-table" data-testid="hierarchy-table">
            <thead>
              <tr>
                <th v-for="column in hierarchyColumns" :key="column">{{ column }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in hierarchyRows" :key="String(row.id)" :data-testid="`hierarchy-${row.成员编码}`">
                <td v-for="column in hierarchyColumns" :key="column">{{ row[column] ?? '—' }}</td>
              </tr>
              <tr v-if="!hierarchyRows.length">
                <td :colspan="hierarchyColumns.length" class="empty-state">暂无层级索引数据</td>
              </tr>
            </tbody>
          </table>
        </article>

        <article class="merge-card">
          <h4>④ 下游汇总核对（按成员计数不重复）</h4>
          <div class="stat-row">
            <div class="stat-card">
              <span class="stat-label">索引行数</span>
              <strong class="stat-value">{{ summary.索引行数 ?? 0 }}</strong>
            </div>
            <div class="stat-card">
              <span class="stat-label">去重成员数</span>
              <strong class="stat-value">{{ summary.去重成员数 ?? 0 }}</strong>
            </div>
            <div class="stat-card">
              <span class="stat-label">重复成员数</span>
              <strong class="stat-value" :class="summary.重复成员数 ? 'error-text' : 'ok-text'">{{ summary.重复成员数 ?? 0 }}</strong>
            </div>
          </div>
          <p class="merge-message" :class="summary.重复成员数 ? 'error-text' : 'ok-text'" data-testid="summary-verdict">
            {{ summary.核对结论 || '—' }}
          </p>
          <table class="data-table">
            <thead>
              <tr>
                <th>父路径</th>
                <th>成员数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in summary.按父级汇总 || []" :key="String(item.父路径)">
                <td>{{ item.父路径 }}</td>
                <td>{{ item.成员数 }}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="(summary.重复成员 || []).length" class="merge-detail">
            <h5>仍存在多条父路径的成员</h5>
            <table class="data-table">
              <thead>
                <tr>
                  <th>成员编码</th>
                  <th>成员名称</th>
                  <th>出现次数</th>
                  <th>父路径列表</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in summary.重复成员" :key="String(item.成员编码)">
                  <td>{{ item.成员编码 }}</td>
                  <td>{{ item.成员名称 }}</td>
                  <td>{{ item.出现次数 }}</td>
                  <td>{{ (item.父路径列表 || []).join('；') }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>
      </div>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条维度管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type MergeRecordResult = { import_id: number; ok: boolean; message: string }
type ImportRecordResult = { 序号: number; ok: boolean; message: string }
type SourceInput = { import_id: number; 导入批次: string; 来源部门: string; 成员编码: string; 成员名称: string; 父路径: string }
type CandidatePath = { 父路径: string; 来源部门: string; 来源类型: string; 落库时间: string; 路径深度: number }
type MemberMergeDetail = { 成员编码: string; 成员名称: string; 候选父路径: CandidatePath[]; 选定父路径: string; 是否冲突: boolean; 取舍说明: string }
type MergeDetail = {
  合并批次: string
  合并策略: string
  索引版本: string
  来源输入: SourceInput[]
  成员合并明细: MemberMergeDetail[]
  逐条结果: MergeRecordResult[]
}

const ENDPOINT = '/api/dimension'
const columns = ["维度编号", "维度名称", "维度类型", "关联数据集", "层级结构", "默认取值", "排序规则", "维度状态"]
const actions = ["提交定义", "发布维度", "停用维度"]
const statuses = ["草稿", "已定义", "已发布", "已停用"]
const metricNames = ["已发布维度", "草稿维度", "停用维度"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const stats = computed(() => [
  { label: metricNames[0], value: total.value },
  { label: metricNames[1], value: rows.value.filter((row) => row.status === statuses[1]).length },
  { label: metricNames[2], value: rows.value.filter((row) => row.status === statuses[statuses.length - 1]).length },
])

// 维度层级合并：来源明细 → 批次合并结果 → 单一维度层级索引 → 下游汇总核对
const strategies = ["按导入落库先后", "按父路径深度"]
const importColumns = ["导入批次", "来源部门", "成员编码", "成员名称", "父路径", "导入时间", "status"]
const mergeColumns = ["合并批次", "合并策略", "输入记录数", "成功记录数", "失败记录数", "成员数", "冲突成员数", "索引版本", "status"]
const hierarchyColumns = ["索引版本", "成员编码", "成员名称", "父路径", "路径深度", "来源部门", "合并批次"]
const importFormFields = ["导入批次", "来源部门", "成员编码", "成员名称", "父路径"]

const importRows = ref<Row[]>([])
const selectedImportIds = ref<number[]>([])
const mergeStrategy = ref(strategies[0])
const merging = ref(false)
const importing = ref(false)
const mergeRows = ref<Row[]>([])
const mergeDetail = ref<MergeDetail | null>(null)
const mergeMessage = ref('')
const mergeRecordResults = ref<MergeRecordResult[]>([])
const importResults = ref<ImportRecordResult[]>([])
const importForm = ref<Record<string, string>>({})
const hierarchyRows = ref<Row[]>([])
const hierarchyVersion = ref('')
const summary = ref<Record<string, any>>({})

const allSelected = computed(() => importRows.value.length > 0 && selectedImportIds.value.length === importRows.value.length)
const mergeDetailSourceText = computed(() => {
  const inputs = mergeDetail.value?.来源输入 ?? []
  if (!inputs.length) return '—'
  return inputs.map((item) => `#${item.import_id} ${item.来源部门} ${item.成员编码}→${item.父路径}`).join('；')
})

function toggleSelectAll() {
  selectedImportIds.value = allSelected.value ? [] : importRows.value.map((row) => Number(row.id))
}

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value).toString()
  try {
    const response = await request(`${ENDPOINT}/export?${query}`)
    if (!response.ok) throw new Error('导出失败，请稍后重试')
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = 'dimension.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(columns.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST', body: JSON.stringify(createValues.value),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '登记失败')
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('维度管理动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '维度管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('分析维度列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '维度管理列表读取失败'
  }
}

async function reloadImports() {
  const response = await request(`${ENDPOINT}/imports`)
  const payload = await response.json()
  importRows.value = payload.items ?? []
}

async function reloadMerges() {
  const response = await request(`${ENDPOINT}/merges`)
  const payload = await response.json()
  mergeRows.value = payload.items ?? []
}

async function reloadHierarchy() {
  const response = await request(`${ENDPOINT}/hierarchy`)
  const payload = await response.json()
  hierarchyRows.value = payload.items ?? []
  hierarchyVersion.value = payload.索引版本 ?? ''
}

async function reloadSummary() {
  const response = await request(`${ENDPOINT}/hierarchy/summary`)
  summary.value = await response.json()
}

async function reloadMergePanels() {
  await Promise.all([reloadImports(), reloadMerges(), reloadHierarchy(), reloadSummary()])
}

async function runMerge() {
  merging.value = true
  mergeMessage.value = ''
  mergeRecordResults.value = []
  try {
    const response = await request(`${ENDPOINT}/merges`, {
      method: 'POST',
      body: JSON.stringify({ import_ids: selectedImportIds.value, strategy: mergeStrategy.value }),
    })
    const payload = await response.json()
    mergeMessage.value = payload.message || ''
    const entry = payload.entry || {}
    mergeRecordResults.value = (entry.逐条结果 || []) as MergeRecordResult[]
    if (!response.ok || !payload.ok) throw new Error(payload.message || '合并失败')
    mergeDetail.value = entry
    await reloadMergePanels()
  } catch (error) {
    mergeMessage.value = error instanceof Error ? error.message : '维度批次合并失败'
  } finally {
    merging.value = false
  }
}

async function openMergeDetail(mergeId: number) {
  mergeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/merges/${mergeId}`)
    if (!response.ok) throw new Error('维度批次合并结果读取失败')
    mergeDetail.value = await response.json()
  } catch (error) {
    mergeMessage.value = error instanceof Error ? error.message : '维度批次合并结果读取失败'
  }
}

async function submitImport() {
  importing.value = true
  importResults.value = []
  try {
    const record = {
      ...importForm.value,
      维度编号: 'DIME-0001',
      维度名称: '组织架构维度',
      导入时间: new Date().toISOString().slice(0, 19).replace('T', ' '),
    }
    const response = await request(`${ENDPOINT}/imports`, {
      method: 'POST',
      body: JSON.stringify({ records: [record] }),
    })
    const payload = await response.json()
    const entry = payload.entry || {}
    importResults.value = (entry.逐条结果 || []) as ImportRecordResult[]
    if (!response.ok || !payload.ok) throw new Error(payload.message || '批量导入失败')
    importForm.value = {}
    await reloadImports()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量导入失败'
  } finally {
    importing.value = false
  }
}

onMounted(() => {
  void reload()
  void reloadMergePanels()
})
</script>

<style scoped>
.merge-section {
  margin-top: 24px;
  border-top: 2px solid var(--border);
  padding-top: 8px;
}
.merge-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}
.merge-card {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
}
.merge-card h4 {
  margin: 0 0 10px;
  font-size: 14px;
}
.merge-card h5 {
  margin: 12px 0 8px;
  font-size: 13px;
}
.merge-toolbar {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  margin-bottom: 10px;
}
.merge-toolbar select {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
}
.import-form {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: flex-end;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--border);
}
.result-list {
  margin: 8px 0 0;
  padding-left: 18px;
  font-size: 12px;
}
.merge-message {
  font-size: 13px;
  margin: 8px 0;
}
.merge-detail {
  margin-top: 10px;
  border-top: 1px dashed var(--border);
  padding-top: 8px;
}
.candidate-path {
  display: block;
  font-size: 12px;
}
.ok-text {
  color: #15803d;
}
@media (max-width: 1200px) {
  .merge-grid {
    grid-template-columns: 1fr;
  }
}
</style>
