<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../lib/api';
import { renderInlineMarkdownHtml } from '../lib/markdown';
import type { ExerciseAttempt, Lesson } from '../lib/types';

const router = useRouter();
const lessons = ref<Lesson[]>([]);
const attempts = ref<ExerciseAttempt[]>([]);
const loading = ref(true);
const error = ref('');
const success = ref('');
const deletingLessonId = ref<number | null>(null);
const activeCourse = ref('all');
const groups = computed(() => {
  const source = activeCourse.value === 'all' ? lessons.value : lessons.value.filter(item => item.course_name === activeCourse.value);
  return [...new Set(source.map(item => item.course_name))].map(name => ({ name, items: source.filter(item => item.course_name === name) }));
});
const attemptGroups = computed(() => {
  const source = activeCourse.value === 'all' ? attempts.value : attempts.value.filter(item => item.course_name === activeCourse.value);
  return [...new Set(source.map(item => item.course_name))].map(name => ({ name, items: source.filter(item => item.course_name === name) }));
});
const courseNames = computed(() => [...new Set([
  ...lessons.value.map(item => item.course_name),
  ...attempts.value.map(item => item.course_name)
])].sort());

function dateLabel(value: string) {
  return new Intl.DateTimeFormat('vi-VN', { day: '2-digit', month: 'long', year: 'numeric' }).format(new Date(value));
}

function dateTimeLabel(value: string) {
  return new Intl.DateTimeFormat('vi-VN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

function preview(content: string) {
  return content.replace(/^#+\s/gm, '').replace(/[*_`>#]/g, '').replace(/\n+/g, ' ').slice(0, 150);
}

async function deleteLesson(lesson: Lesson) {
  if (deletingLessonId.value !== null) return;
  const confirmed = window.confirm(
    `Xóa bài giảng "${lesson.title}"? Toàn bộ hỏi đáp và kết quả nộp bài liên quan cũng sẽ bị xóa. Thao tác này không thể hoàn tác.`
  );
  if (!confirmed) return;

  deletingLessonId.value = lesson.id;
  error.value = '';
  success.value = '';
  try {
    await api.delete<{ message: string }>(`/lessons/${lesson.id}`);
    lessons.value = lessons.value.filter(item => item.id !== lesson.id);
    attempts.value = attempts.value.filter(item => item.lesson_id !== lesson.id);
    success.value = `Đã xóa bài giảng "${lesson.title}" cùng dữ liệu liên quan.`;
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Không xóa được bài giảng.';
  } finally {
    deletingLessonId.value = null;
  }
}

onMounted(async () => {
  try {
    [lessons.value, attempts.value] = await Promise.all([
      api.get<Lesson[]>('/lessons?limit=200'),
      api.get<ExerciseAttempt[]>('/exercise-attempts?limit=500')
    ]);
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Không tải được lịch sử học.';
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="page-wrap history-page">
    <section class="page-heading history-heading"><div><div class="eyebrow"><span class="eyebrow-line"></span> YOUR LEARNING JOURNEY</div><h1>Nhìn lại những điều <em>bạn đã khám phá.</em></h1><p>Mỗi bài học đã lưu là một bước tiến. Cứ tiếp tục nhé.</p></div><div class="heading-stamp history-stamp"><span>◷</span><small>LEARN<br />REFLECT</small></div></section>
    <div v-if="error" class="notice notice-error">{{ error }}<button @click="error = ''">×</button></div>
    <div v-if="success" class="notice notice-success">{{ success }}<button @click="success = ''">×</button></div>
    <section class="history-toolbar"><div class="history-count"><strong>{{ lessons.length }}</strong><span>bài học đã lưu</span><strong>{{ attempts.length }}</strong><span>lượt nộp bài</span><span class="count-flower">✳</span></div><div class="filter-pills"><button :class="{ active: activeCourse === 'all' }" @click="activeCourse = 'all'">Tất cả môn</button><button v-for="course in courseNames" :key="course" :class="{ active: activeCourse === course }" @click="activeCourse = course">{{ course }}</button></div></section>
    <div v-if="loading" class="loading-card">Đang mở lại hành trình học tập…</div>
    <div v-else-if="!lessons.length" class="history-empty surface-card"><div class="empty-clock">◷</div><span class="preview-label">MỌI HÀNH TRÌNH ĐỀU CÓ ĐIỂM BẮT ĐẦU</span><h2>Chưa có bài học nào ở đây.</h2><p>Tạo bài học đầu tiên và nội dung sẽ được lưu để bạn quay lại bất cứ lúc nào.</p><RouterLink to="/learn" class="button button-primary">Tạo bài học đầu tiên <span>→</span></RouterLink></div>
    <div v-else class="history-groups">
      <section v-for="group in groups" :key="group.name" class="history-group">
        <div class="group-heading"><div class="group-subject-icon">{{ group.name.slice(0, 1) }}</div><div><h2>{{ group.name }}</h2><p>{{ group.items.length }} bài học <span>·</span> Lưu theo môn học</p></div><div class="group-line"></div><span class="group-star">✳</span></div>
        <div class="history-cards">
          <article v-for="(item, index) in group.items" :key="item.id" class="history-card surface-card">
            <button class="history-card-open" type="button" @click="router.push(`/learn/${item.id}`)">
              <div class="history-card-top"><span class="history-index">{{ String(index + 1).padStart(2, '0') }}</span><time>{{ dateLabel(item.created_at) }}</time><span class="card-arrow">↗</span></div>
              <h3>{{ item.title }}</h3>
              <p>{{ preview(item.content) }}{{ item.content.length > 150 ? '…' : '' }}</p>
              <div class="history-card-bottom"><span class="history-class-chip">⌂ {{ item.classroom_name }}</span><span class="history-exercise-chip">✎ {{ item.exercises.length }} bài tập</span></div>
            </button>
            <div class="history-card-actions"><button class="history-delete-button" type="button" :disabled="deletingLessonId !== null" @click="deleteLesson(item)">{{ deletingLessonId === item.id ? 'Đang xóa…' : 'Xóa bài giảng' }}</button></div>
          </article>
        </div>
      </section>
    </div>
    <section v-if="!loading" class="attempt-history-section">
      <div class="group-heading attempt-section-heading"><div class="group-subject-icon">✓</div><div><h2>Kết quả nộp bài</h2><p>{{ attempts.length }} lượt nộp được lưu</p></div><div class="group-line"></div><span class="group-star">◷</span></div>
      <div v-if="!attempts.length" class="attempts-empty surface-card">Chưa có lượt nộp bài nào. Sau khi nộp bài tập, kết quả sẽ xuất hiện ở đây.</div>
      <div v-else class="history-groups attempt-history-groups">
        <section v-for="group in attemptGroups" :key="group.name" class="history-group">
          <div class="group-heading"><div class="group-subject-icon">{{ group.name.slice(0, 1) }}</div><div><h2>{{ group.name }}</h2><p>{{ group.items.length }} lượt nộp <span>·</span> Kết quả theo môn học</p></div><div class="group-line"></div></div>
          <details v-for="attempt in group.items" :key="attempt.id" class="attempt-history-card surface-card">
            <summary class="attempt-history-summary"><div class="attempt-summary-copy"><div class="attempt-card-top"><time>{{ dateTimeLabel(attempt.submitted_at) }}</time><span class="attempt-difficulty">{{ attempt.total_questions }} câu</span></div><h3>{{ attempt.lesson_title }}</h3><p v-if="attempt.objective_count">Đúng {{ attempt.correct_count }}/{{ attempt.objective_count }} câu trắc nghiệm<span v-if="attempt.score_percent !== null"> · {{ attempt.score_percent }}%</span><span v-if="attempt.written_count"> · {{ attempt.written_count }} câu tự luận</span></p><p v-else>{{ attempt.written_count }} câu tự luận đã ghi nhận</p></div><span class="attempt-open">Xem chi tiết <b>⌄</b></span></summary>
            <div class="attempt-review">
              <article v-for="(result, index) in attempt.results" :key="index" class="attempt-review-item">
                <span class="attempt-question-number">Câu {{ index + 1 }}</span><strong v-html="renderInlineMarkdownHtml(result.question)"></strong>
                <p class="attempt-response"><b>Trả lời của học sinh:</b> <span v-html="renderInlineMarkdownHtml(result.response)"></span></p>
                <p v-if="result.correct !== null" :class="result.correct ? 'attempt-correct' : 'attempt-incorrect'">{{ result.correct ? '✓ Trả lời chính xác' : '• Chưa chính xác' }}</p>
                <p><b>Đáp án tham khảo:</b> <span v-html="renderInlineMarkdownHtml(result.answer)"></span></p><small v-html="renderInlineMarkdownHtml(result.explanation)"></small>
              </article>
              <RouterLink :to="`/learn/${attempt.lesson_id}`" class="text-button">Mở lại bài học <span>↗</span></RouterLink>
            </div>
          </details>
        </section>
      </div>
    </section>
    <footer v-if="lessons.length" class="history-footer"><span>✧</span> Bạn đang đi đúng hướng — một bài học tại một thời điểm.</footer>
  </div>
</template>
