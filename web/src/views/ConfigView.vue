<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { api } from '../lib/api';
import type { AppSettings, Course, CourseLessonTitleSyncResult, Material } from '../lib/types';

const settings = ref<AppSettings | null>(null);
const savedClassroomId = ref<number | null>(null);
const activeCourseId = ref<number | null>(null);
const apiKey = ref('');
const clearKey = ref(false);
const busy = ref(false);
const uploadBusy = ref(false);
const deletingMaterialId = ref<number | null>(null);
const syncingCourseId = ref<number | null>(null);
const MAX_UPLOAD_MB = 20;
const error = ref('');
const success = ref('');
const activeCourse = computed<Course | undefined>(() => settings.value?.courses.find(course => course.id === activeCourseId.value));

function materialSummary(material: Material): string {
  if (material.processing_status === 'queued') return 'Đang chờ worker nhận dạng chữ…';
  if (material.processing_status === 'processing') return 'Đang nhận dạng chữ…';
  if (material.processing_status === 'failed') return material.processing_error || 'Không xử lý được PDF.';
  if (material.processing_status === 'legacy' && material.section_count === 0) return 'Tài liệu cũ · chưa tách bài';
  if (material.section_count === 0) return 'Đã lưu toàn văn · chưa nhận diện bài';
  return material.lesson_count > 0
    ? 'Đã nhận diện và lưu ' + material.lesson_count + ' bài'
    : 'Đã lưu nội dung · chưa nhận diện bài';
}

let statusPollTimer: number | undefined;
let statusPollBusy = false;

function syncStatusPolling() {
  const hasPendingJobs = settings.value?.courses.some(course =>
    course.materials.some(material =>
      material.processing_status === 'queued' || material.processing_status === 'processing'
    )
  ) ?? false;

  if (hasPendingJobs && statusPollTimer === undefined) {
    statusPollTimer = window.setInterval(async () => {
      if (statusPollBusy) return;
      statusPollBusy = true;
      try {
        await load(true);
      } finally {
        statusPollBusy = false;
      }
    }, 3000);
  } else if (!hasPendingJobs && statusPollTimer !== undefined) {
    window.clearInterval(statusPollTimer);
    statusPollTimer = undefined;
  }
}

function updateProviderDefaults() {
  if (!settings.value) return;
  if (settings.value.provider === 'ollama') {
    if (settings.value.base_url === 'https://api.openai.com/v1') settings.value.base_url = 'http://localhost:11434/v1';
    if (settings.value.model === 'gpt-4o-mini') settings.value.model = 'llama3.2';
  } else if (settings.value.provider === 'openai' && settings.value.base_url === 'http://localhost:11434/v1') {
    settings.value.base_url = 'https://api.openai.com/v1';
    if (settings.value.model === 'llama3.2') settings.value.model = 'gpt-4o-mini';
  }
}

async function load(preserveClassSelection = false) {
  try {
    const selectedClassroomId = settings.value?.classroom_id;
    const loadedSettings = await api.get<AppSettings>('/settings');
    savedClassroomId.value = loadedSettings.classroom_id;
    if (
      preserveClassSelection
      && selectedClassroomId !== undefined
      && selectedClassroomId !== loadedSettings.classroom_id
    ) {
      loadedSettings.classroom_id = selectedClassroomId;
    }
    settings.value = loadedSettings;
    activeCourseId.value ??= settings.value.courses[0]?.id ?? null;
    syncStatusPolling();
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Không tải được cấu hình.';
  }
}

async function save() {
  if (!settings.value?.classroom_id) {
    error.value = 'Hãy chọn lớp học trước khi lưu.';
    return;
  }
  const classroomChanged = savedClassroomId.value !== null
    && savedClassroomId.value !== settings.value.classroom_id;
  const materialCount = settings.value.courses.reduce(
    (total, course) => total + course.materials.length,
    0
  );
  if (classroomChanged && materialCount > 0) {
    const confirmed = window.confirm(
      `Đổi lớp sẽ xóa toàn bộ ${materialCount} tài liệu PDF đã tải lên cùng dữ liệu OCR. Bài giảng và lịch sử học tập vẫn được giữ. Bạn có muốn tiếp tục?`
    );
    if (!confirmed) return;
  }
  busy.value = true;
  error.value = '';
  success.value = '';
  try {
    const updatedSettings = await api.put<AppSettings>('/settings', {
      classroom_id: settings.value.classroom_id,
      provider: settings.value.provider,
      model: settings.value.model,
      base_url: settings.value.base_url,
      api_key: apiKey.value || null,
      clear_api_key: clearKey.value,
      prompts: settings.value.courses.map(course => ({ course_id: course.id, prompt: course.prompt || '' }))
    });
    settings.value = updatedSettings;
    savedClassroomId.value = updatedSettings.classroom_id;
    apiKey.value = '';
    clearKey.value = false;
    success.value = classroomChanged && (updatedSettings.materials_removed ?? 0) > 0
      ? `Đã lưu cấu hình và xóa ${updatedSettings.materials_removed} tài liệu cũ. Bài giảng và lịch sử vẫn được giữ.`
      : 'Cấu hình đã được lưu.';
    if (updatedSettings.material_cleanup_warning) {
      error.value = updatedSettings.material_cleanup_warning;
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Không lưu được cấu hình.';
  } finally {
    busy.value = false;
  }
}

async function deleteMaterial(material: Material) {
  if (deletingMaterialId.value !== null || uploadBusy.value) return;
  const confirmed = window.confirm(
    `Xóa tài liệu "${material.file_name}"? File PDF, nội dung các bài đã trích xuất và trạng thái OCR sẽ bị xóa. Bài giảng đã tạo trước đó vẫn được giữ lại.`
  );
  if (!confirmed) return;

  deletingMaterialId.value = material.id;
  error.value = '';
  success.value = '';
  try {
    await api.delete<{ message: string }>(`/materials/${material.id}`);
    await load();
    success.value = `Đã xóa tài liệu "${material.file_name}" cùng dữ liệu liên quan.`;
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Không xóa được tài liệu.';
  } finally {
    deletingMaterialId.value = null;
  }
}

async function syncLessonTitles(courseId: number) {
  if (!settings.value?.classroom_id) {
    error.value = 'Hãy chọn lớp học trước khi đồng bộ tiêu đề.';
    return;
  }
  if (syncingCourseId.value !== null) return;

  syncingCourseId.value = courseId;
  error.value = '';
  success.value = '';
  const courseName = settings.value.courses.find(course => course.id === courseId)?.name || 'bài học';
  try {
    const result = await api.post<CourseLessonTitleSyncResult>(
      `/courses/${courseId}/lesson-titles/sync?classroom_id=${settings.value.classroom_id}`
    );
    const volumes = [...new Set(result.titles.map(item => item.volume).filter((item): item is number => item !== null))];
    const volumeLabel = volumes.length ? ` · Tập ${volumes.join(' + ')}` : '';
    success.value = `Đã đồng bộ ${result.count} tiêu đề ${courseName}${volumeLabel} cho ${settings.value.classes.find(item => item.id === result.classroom_id)?.name || 'lớp đã chọn'}.`;
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Không đồng bộ được tiêu đề bài học.';
  } finally {
    syncingCourseId.value = null;
  }
}

async function uploadMaterial(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file || !activeCourseId.value) return;
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    error.value = `File quá lớn. Giới hạn tải lên là ${MAX_UPLOAD_MB} MB. Vui lòng chọn file nhỏ hơn.`;
    input.value = '';
    return;
  }
  const form = new FormData();
  form.set('file', file);
  uploadBusy.value = true;
  error.value = '';
  success.value = '';
  try {
    await api.upload<{ id: number }>('/materials?course_id=' + activeCourseId.value, form);
    await load();
    success.value = 'Đã tải ' + file.name + '. Hệ thống đang nhận dạng nội dung trong nền.';
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Không tải được file.';
  } finally {
    uploadBusy.value = false;
    input.value = '';
  }
}

onMounted(load);
onUnmounted(() => {
  if (statusPollTimer !== undefined) window.clearInterval(statusPollTimer);
});
</script>

<template>
  <div class="page-wrap config-page">
    <section class="page-heading">
      <div><div class="eyebrow"><span class="eyebrow-line"></span> THIẾT LẬP CỦA BẠN</div><h1>Một không gian học <em>vừa vặn.</em></h1><p>Điều chỉnh gia sư AI, lớp học và tài liệu để mỗi bài học đều bắt đầu đúng chỗ.</p></div>
      <div class="heading-stamp"><span>✳</span><small>MADE FOR<br />YOUR PACE</small></div>
    </section>
    <div v-if="error" class="notice notice-error">{{ error }}</div>
    <div v-if="success" class="notice notice-success">{{ success }}</div>
    <div v-if="!settings" class="loading-card">Đang tải cấu hình học tập…</div>
    <template v-else>
      <section class="config-grid">
        <article class="surface-card config-card ai-config-card">
          <div class="section-head"><div class="section-icon violet-icon">✧</div><div><h2>Gia sư AI</h2><p>Chọn mô hình đồng hành cùng bạn.</p></div><span class="optional-tag">CÁ NHÂN HÓA</span></div>
          <div class="field-grid">
            <label class="field-label">AI provider
              <select v-model="settings.provider" @change="updateProviderDefaults">
                <option value="demo">Demo · dùng thử miễn phí</option><option value="openai">OpenAI</option><option value="ollama">Ollama · local</option><option value="custom">Tùy chỉnh · OpenAI-compatible</option>
              </select>
            </label>
            <label class="field-label">Tên model<input v-model="settings.model" placeholder="gpt-4o-mini" /></label>
            <label class="field-label field-full">API endpoint
              <input v-model="settings.base_url" :placeholder="settings.provider === 'ollama' ? 'http://localhost:11434/v1' : 'https://api.openai.com/v1'" />
              <small class="field-help">Ollama: http://localhost:11434/v1 · API tương thích OpenAI: URL gốc hoặc /chat/completions</small>
            </label>
            <label class="field-label field-full">API key <span class="label-muted">{{ settings.has_api_key ? '· Đã lưu an toàn' : '· Chưa cấu hình' }}</span>
              <input v-model="apiKey" type="password" autocomplete="new-password" :placeholder="settings.has_api_key ? 'Nhập key mới để thay đổi' : 'Nhập API key của bạn'" />
              <small class="field-help">Key được mã hóa trước khi lưu và không hiển thị lại sau khi thiết lập.</small>
            </label>
            <label v-if="settings.has_api_key" class="check-row field-full"><input v-model="clearKey" type="checkbox" /> Xóa API key đã lưu</label>
          </div>
          <div class="demo-note"><span>✦</span><p>Chọn <strong>Demo</strong> để trải nghiệm các luồng học tập mà chưa cần kết nối AI.</p></div>
        </article>
        <article class="surface-card config-card class-config-card">
          <div class="section-head"><div class="section-icon green-icon">⌂</div><div><h2>Lớp học của bạn</h2><p>Mỗi người học chọn một lớp.</p></div></div>
          <label class="field-label">Chọn lớp
            <select v-model.number="settings.classroom_id"><option :value="null" disabled>Chọn lớp của bạn</option><option v-for="item in settings.classes" :key="item.id" :value="item.id">{{ item.name }} · {{ item.level }}</option></select>
          </label>
          <div class="class-preview"><div class="preview-decoration">✳</div><span class="preview-label">LỘ TRÌNH CÁ NHÂN</span><strong>{{ settings.classes.find(item => item.id === settings?.classroom_id)?.name || 'Chọn lớp để bắt đầu' }}</strong><small>Nội dung được điều chỉnh theo độ tuổi và kiến thức nền.</small></div>
        </article>
      </section>
      <section class="surface-card subject-config-card">
        <div class="section-head subject-head"><div class="section-icon peach-icon">▤</div><div><h2>Ngữ cảnh theo môn học</h2><p>Thêm tài liệu tham khảo và hướng dẫn riêng cho gia sư.</p></div><span class="subject-count">{{ settings.courses.length }} môn học</span></div>
        <div class="subject-workspace">
          <aside class="subject-list">
            <button v-for="course in settings.courses" :key="course.id" class="subject-tab" :class="{ active: course.id === activeCourseId }" @click="activeCourseId = course.id">
              <span class="subject-bullet">{{ course.name.slice(0, 1) }}</span><span><strong>{{ course.name }}</strong><small>{{ course.materials.length ? `${course.materials.length} tài liệu` : 'Chưa có tài liệu' }}</small></span><span v-if="course.id === activeCourseId" class="tab-chevron">›</span>
            </button>
          </aside>
          <div v-if="activeCourse" class="subject-editor">
            <div class="subject-editor-heading"><div><span class="preview-label">MÔN HỌC</span><h3>{{ activeCourse.name }}</h3><p>{{ activeCourse.description }}</p></div><span class="course-glyph">{{ activeCourse.name.slice(0, 1) }}</span></div>
            <label class="field-label prompt-label">Prompt riêng <span class="label-muted">· Không bắt buộc</span>
              <textarea v-model="activeCourse.prompt" rows="5" placeholder="Ví dụ: Giải thích bằng ngôn ngữ gần gũi, luôn đưa ví dụ thực tế và đặt câu hỏi gợi mở sau mỗi phần…"></textarea>
              <small class="field-help">Để trống nếu muốn dùng hướng dẫn mặc định. Prompt này được thêm vào khi tạo bài học và bài tập.</small>
            </label>
            <div class="lesson-title-sync">
              <div><strong>Tiêu đề bài học</strong><small>Đồng bộ từ PDF Kết nối tri thức đã tải lên, có thể gồm cả Tập 1 và Tập 2.</small></div>
              <button class="button button-secondary" type="button" :disabled="!settings.classroom_id || syncingCourseId !== null" @click="syncLessonTitles(activeCourse.id)">{{ syncingCourseId === activeCourse.id ? 'Đang đồng bộ…' : 'Đồng bộ tiêu đề' }}</button>
            </div>
            <div class="materials-heading"><div><strong>Tài liệu môn học</strong><small>PDF · tối đa 20 MB mỗi file</small></div><label class="button button-secondary upload-button" :class="{ disabled: uploadBusy }">{{ uploadBusy ? 'Đang tải…' : '＋ Tải PDF lên' }}<input type="file" accept="application/pdf,.pdf" :disabled="uploadBusy" @change="uploadMaterial" /></label></div>
            <div v-if="activeCourse.materials.length" class="material-list">
              <div v-for="material in activeCourse.materials" :key="material.id" class="material-item">
                <span class="pdf-icon">PDF</span>
                <div><strong>{{ material.file_name }}</strong><small>{{ materialSummary(material) }}</small></div>
                <span class="material-check" :class="'material-status-' + material.processing_status">{{ material.processing_status === 'failed' ? '!' : material.processing_status === 'completed' || material.processing_status === 'legacy' ? '✓' : '…' }}</span>
                <button class="material-delete" type="button" :disabled="deletingMaterialId !== null || uploadBusy" :aria-label="'Xóa tài liệu ' + material.file_name" title="Xóa tài liệu" @click="deleteMaterial(material)">{{ deletingMaterialId === material.id ? '…' : '×' }}</button>
              </div>
            </div>
            <div v-else class="materials-empty"><span>↥</span><p>Chưa có tài liệu cho môn học này.</p><small>Thêm PDF để gia sư có thể bám sát tài liệu lớp bạn.</small></div>
          </div>
        </div>
      </section>
      <div class="config-footer"><p><span>✧</span> Thiết lập có thể thay đổi bất cứ lúc nào.</p><button class="button button-primary" :disabled="busy" @click="save">{{ busy ? 'Đang lưu…' : 'Lưu cấu hình' }} <span>→</span></button></div>
    </template>
  </div>
</template>
