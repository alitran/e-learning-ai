<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../lib/api';
import { renderInlineMarkdownHtml, renderMarkdownHtml } from '../lib/markdown';
import type { AppSettings, CourseLessonTitle, Exercise, ExerciseAttempt, ExerciseAttemptResult, Lesson, LessonMessage } from '../lib/types';

const route = useRoute();
const router = useRouter();
const settings = ref<AppSettings | null>(null);
const lesson = ref<Lesson | null>(null);
const messages = ref<LessonMessage[]>([]);
const attemptHistory = ref<ExerciseAttempt[]>([]);
const currentAttempt = ref<ExerciseAttempt | null>(null);
const courseId = ref<number | null>(null);
const title = ref('');
const lessonTitles = ref<CourseLessonTitle[]>([]);
const titleSelection = ref('');
const loadingLessonTitles = ref(false);
const question = ref('');
const difficulty = ref<'easy' | 'medium' | 'hard'>('easy');
const exerciseCount = ref(5);
const instructions = ref('');
const studentAnswers = ref<Record<number, string>>({});
const exerciseEditMode = ref<Record<number, boolean>>({});
const exerciseChangesPending = ref(false);
const exercisesSubmitted = ref(false);
const loadingLesson = ref(false);
const loadingExercises = ref(false);
const asking = ref(false);
const savingExercises = ref(false);
const submittingExercises = ref(false);
const error = ref('');
const success = ref('');
const CUSTOM_LESSON_TITLE = '__custom__';
const lessonTitleValue = computed(() => titleSelection.value === CUSTOM_LESSON_TITLE ? title.value : titleSelection.value);
const lessonHtml = computed(() => lesson.value ? renderMarkdownHtml(lesson.value.content) : '');
const correctExerciseCount = computed(() => currentAttempt.value?.correct_count ?? 0);

function attemptResult(index: number): ExerciseAttemptResult | undefined {
  return currentAttempt.value?.results[index];
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('vi-VN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

function clearExerciseAttempt() {
  studentAnswers.value = {};
  exercisesSubmitted.value = false;
  currentAttempt.value = null;
}

async function submitExercises() {
  const exercises = lesson.value?.exercises ?? [];
  const unanswered = exercises.filter((_, index) => !studentAnswers.value[index]?.trim()).length;
  if (unanswered) {
    error.value = 'Bạn còn ' + unanswered + ' câu chưa trả lời.';
    success.value = '';
    return;
  }
  error.value = '';
  submittingExercises.value = true;
  try {
    const savedAttempt = await api.post<ExerciseAttempt>(`/lessons/${lesson.value?.id}/exercise-attempts`, {
      answers: exercises.map((_, index) => studentAnswers.value[index].trim())
    });
    currentAttempt.value = savedAttempt;
    attemptHistory.value = [savedAttempt, ...attemptHistory.value.filter(item => item.id !== savedAttempt.id)];
    exercisesSubmitted.value = true;
    success.value = 'Đã nộp bài và lưu kết quả vào lịch sử.';
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Chưa nộp được bài.';
  } finally {
    submittingExercises.value = false;
  }
}

async function loadLesson(id: string | string[] | undefined) {
  clearExerciseAttempt();
  exerciseEditMode.value = {};
  exerciseChangesPending.value = false;
  if (!id || typeof id !== 'string') {
    lesson.value = null;
    messages.value = [];
    attemptHistory.value = [];
    return;
  }
  try {
    lesson.value = await api.get<Lesson>(`/lessons/${id}`);
    courseId.value = lesson.value.course_id;
    await loadLessonTitles();
    if (lessonTitles.value.some(item => item.title === lesson.value?.title)) {
      titleSelection.value = lesson.value.title;
      title.value = '';
    } else {
      titleSelection.value = CUSTOM_LESSON_TITLE;
      title.value = lesson.value.title;
    }
    const [lessonMessages, savedAttempts] = await Promise.all([
      api.get<LessonMessage[]>(`/lessons/${id}/messages`),
      api.get<ExerciseAttempt[]>(`/lessons/${id}/exercise-attempts`)
    ]);
    messages.value = lessonMessages;
    attemptHistory.value = savedAttempts;
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Không tải được bài học.';
  }
}

async function loadSettings() {
  try {
    settings.value = await api.get<AppSettings>('/settings');
    courseId.value ??= settings.value.courses[0]?.id ?? null;
    await loadLessonTitles();
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Không tải được danh sách môn học.';
  }
}

async function loadLessonTitles() {
  lessonTitles.value = [];
  titleSelection.value = CUSTOM_LESSON_TITLE;
  title.value = '';
  const requestedCourseId = courseId.value;
  if (!requestedCourseId || !settings.value?.classroom_id) return;

  loadingLessonTitles.value = true;
  try {
    const titles = await api.get<CourseLessonTitle[]>(`/courses/${requestedCourseId}/lesson-titles`);
    if (requestedCourseId !== courseId.value) return;
    lessonTitles.value = titles;
    if (titles.length) {
      titleSelection.value = titles[0].title;
    }
  } catch (err) {
    if (requestedCourseId === courseId.value) {
      error.value = err instanceof Error ? err.message : 'Không tải được danh sách tiêu đề bài học.';
    }
  } finally {
    loadingLessonTitles.value = false;
  }
}

async function createLesson() {
  const lessonTitle = lessonTitleValue.value.trim();
  if (!courseId.value || lessonTitle.length < 2) return;
  loadingLesson.value = true;
  error.value = '';
  success.value = '';
  try {
    const result = await api.post<Lesson>('/lessons', { course_id: courseId.value, title: lessonTitle });
    lesson.value = result;
    messages.value = [];
    attemptHistory.value = [];
    clearExerciseAttempt();
    router.replace(`/learn/${result.id}`);
    success.value = 'Bài học đã được tạo và lưu vào lịch sử.';
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Chưa thể tạo bài học.';
  } finally {
    loadingLesson.value = false;
  }
}

async function askQuestion() {
  if (!lesson.value || question.value.trim().length < 2) return;
  asking.value = true;
  error.value = '';
  try {
    await api.post(`/lessons/${lesson.value.id}/ask`, { question: question.value.trim() });
    messages.value = await api.get<LessonMessage[]>(`/lessons/${lesson.value.id}/messages`);
    question.value = '';
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Chưa gửi được câu hỏi.';
  } finally {
    asking.value = false;
  }
}

async function generateExercises() {
  if (!lesson.value) return;
  loadingExercises.value = true;
  error.value = '';
  success.value = '';
  try {
    lesson.value.exercises = await api.post<Exercise[]>(`/lessons/${lesson.value.id}/exercises`, {
      difficulty: difficulty.value,
      count: exerciseCount.value,
      instructions: instructions.value.trim()
    });
    clearExerciseAttempt();
    exerciseEditMode.value = {};
    exerciseChangesPending.value = false;
    success.value = 'Bài tập đã được lưu vào bài học.';
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Chưa tạo được bài tập.';
  } finally {
    loadingExercises.value = false;
  }
}

async function saveExercises() {
  if (!lesson.value) return;
  savingExercises.value = true;
  try {
    lesson.value.exercises = await api.patch<Exercise[]>(`/lessons/${lesson.value.id}/exercises`, { exercises: lesson.value.exercises });
    clearExerciseAttempt();
    exerciseEditMode.value = {};
    exerciseChangesPending.value = false;
    success.value = 'Các chỉnh sửa đã được lưu.';
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Chưa lưu được bài tập.';
  } finally {
    savingExercises.value = false;
  }
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('vi-VN', { dateStyle: 'medium' }).format(new Date(value));
}

onMounted(async () => {
  await loadSettings();
  await loadLesson(route.params.lessonId);
});
watch(() => route.params.lessonId, id => loadLesson(id));
</script>

<template>
  <div class="page-wrap learn-page">
    <section class="page-heading learn-heading">
      <div><div class="eyebrow"><span class="eyebrow-line"></span> YOUR LEARNING STUDIO</div><h1>Hôm nay bạn muốn <em>tìm hiểu gì?</em></h1><p>Một chủ đề nhỏ cũng có thể mở ra một thế giới mới.</p></div>
      <div class="heading-stamp learning-stamp"><span>✳</span><small>STAY CURIOUS<br />KEEP GROWING</small></div>
    </section>
    <div v-if="error" class="notice notice-error">{{ error }}<button @click="error = ''">×</button></div>
    <div v-if="success" class="notice notice-success">{{ success }}<button @click="success = ''">×</button></div>
    <div v-if="settings && !settings.classroom_id" class="notice notice-info">Để tạo bài học phù hợp với bạn, hãy chọn lớp trong <RouterLink to="/config">Cấu hình học tập →</RouterLink></div>
    <section class="create-panel surface-card">
      <div class="create-panel-top"><div class="create-symbol">✧</div><div><span class="preview-label">BẮT ĐẦU TỪ ĐIỀU BẠN TÒ MÒ</span><h2>Tạo một bài học mới</h2></div><div class="class-chip"><span>⌂</span>{{ settings?.classes.find(item => item.id === settings?.classroom_id)?.name || 'Chưa chọn lớp' }}</div></div>
      <form class="lesson-create-form" @submit.prevent="createLesson">
        <label class="field-label course-field">Môn học<select v-model.number="courseId" required @change="loadLessonTitles"><option v-for="course in settings?.courses || []" :key="course.id" :value="course.id">{{ course.name }}</option></select></label>
        <label class="field-label topic-field">Bài bạn muốn học
          <select v-if="lessonTitles.length" v-model="titleSelection" required :disabled="loadingLessonTitles">
            <option value="" disabled>Chọn bài học</option>
            <option v-for="item in lessonTitles" :key="item.id" :value="item.title">{{ item.title }}{{ item.volume ? ` · Tập ${item.volume}` : '' }}</option>
            <option :value="CUSTOM_LESSON_TITLE">Nhập tiêu đề khác…</option>
          </select>
          <input v-if="!lessonTitles.length || titleSelection === CUSTOM_LESSON_TITLE" v-model="title" required minlength="2" :placeholder="lessonTitles.length ? 'Nhập tiêu đề bài học khác…' : 'Ví dụ: Phương trình bậc hai, Thì hiện tại hoàn thành…'" />
        </label>
        <button class="button button-primary generate-button" type="submit" :disabled="loadingLesson || !settings?.classroom_id">{{ loadingLesson ? 'Đang soạn bài…' : 'Tạo bài học' }} <span>✦</span></button>
      </form>
      <small v-if="!lessonTitles.length" class="field-help lesson-title-help">Chưa có tiêu đề trong database. Bạn có thể nhập bài muốn học; đồng bộ danh sách tại Cấu hình sau khi tải PDF.</small>
      <div class="form-caption"><span>✧</span> Bài học được cá nhân hóa theo lớp và tài liệu môn học của bạn.</div>
    </section>

    <section v-if="lesson" class="lesson-layout">
      <article class="surface-card lesson-card">
        <div class="lesson-meta"><span class="course-chip">{{ lesson.course_name }}</span><span>{{ formatDate(lesson.created_at) }}</span><span class="meta-separator">·</span><span>{{ lesson.classroom_name }}</span><RouterLink to="/history" class="lesson-history-link">Xem lịch sử ↗</RouterLink></div>
        <div class="lesson-title-row"><div><span class="preview-label">BÀI HỌC CỦA BẠN</span><h2>{{ lesson.title }}</h2></div><span class="lesson-flower">✳</span></div>
        <div class="markdown-content" v-html="lessonHtml"></div>
        <div v-if="lesson.examples?.length" class="example-section"><div class="subsection-title"><span>▤</span><div><span class="preview-label">HỌC QUA VÍ DỤ</span><h3>Thử áp dụng nhé</h3></div></div><div v-for="(example, index) in lesson.examples" :key="index" class="example-card"><div class="example-index">0{{ index + 1 }}</div><div><strong>{{ example.title || `Ví dụ ${index + 1}` }}</strong><div v-if="example.scenario" class="example-rich-text" v-html="renderInlineMarkdownHtml(example.scenario)"></div><ol v-if="example.steps?.length"><li v-for="(step, i) in example.steps" :key="i" v-html="renderInlineMarkdownHtml(step)"></li></ol><div v-if="example.answer" class="example-answer"><b>Gợi ý:</b> <span v-html="renderInlineMarkdownHtml(example.answer)"></span></div></div></div></div>
        <div class="reflection-strip"><span>✧</span><p>Hãy tự giải thích lại một ý chính bằng lời của bạn — đó là cách kiểm tra mức độ hiểu bài rất tốt.</p></div>
      </article>

      <section class="surface-card qa-card"><div class="subsection-title"><span class="qa-icon">↗</span><div><span class="preview-label">HỎI GIA SƯ AI</span><h3>Cùng tìm hiểu sâu hơn</h3></div></div><p class="qa-intro">Có phần nào bạn muốn hỏi thêm? Câu trả lời sẽ dựa trên bài học này.</p><form class="ask-form" @submit.prevent="askQuestion"><input v-model="question" placeholder="Mình chưa hiểu rõ phần…" required minlength="2" /><button class="button button-dark" :disabled="asking">{{ asking ? 'Đang hỏi…' : 'Hỏi' }} <span>→</span></button></form><div v-if="messages.length" class="qa-thread"><article v-for="message in messages" :key="message.id" class="qa-message"><div class="question-bubble"><span class="qa-avatar student-avatar">H</span><p>{{ message.question }}</p></div><div class="answer-bubble"><span class="qa-avatar ai-avatar">✦</span><div class="markdown-content compact-markdown" v-html="renderMarkdownHtml(message.answer)"></div></div></article></div><div v-else class="qa-empty">✧ Cứ hỏi bất kỳ điều gì trong bài học.</div></section>

      <section class="surface-card exercise-card">
        <div class="exercise-header">
          <div class="subsection-title"><span class="exercise-icon">✎</span><div><span class="preview-label">LUYỆN TẬP CHỦ ĐỘNG</span><h3>Đến lượt bạn thử sức</h3></div></div>
          <span class="challenge-stamp">ONE STEP<br />AT A TIME</span>
        </div>
        <p class="exercise-intro">Chọn độ khó phù hợp. Bạn có thể tạo lại hoặc chỉnh sửa bài tập bất cứ lúc nào.</p>
        <div class="exercise-controls">
          <div class="difficulty-control">
            <button v-for="item in [{ id: 'easy', label: 'Dễ', icon: '○' }, { id: 'medium', label: 'Vừa', icon: '◐' }, { id: 'hard', label: 'Khó', icon: '●' }]" :key="item.id" :class="{ active: difficulty === item.id }" @click="difficulty = item.id as 'easy' | 'medium' | 'hard'"><span>{{ item.icon }}</span>{{ item.label }}</button>
          </div>
          <label class="count-control">Số câu<select v-model.number="exerciseCount"><option :value="3">3 câu</option><option :value="5">5 câu</option><option :value="8">8 câu</option><option :value="10">10 câu</option></select></label>
          <button class="button button-primary" :disabled="loadingExercises" @click="generateExercises">{{ loadingExercises ? 'Đang tạo…' : lesson.exercises.length ? 'Tạo bộ khác' : 'Tạo bài tập' }} <span>✦</span></button>
        </div>
        <label class="field-label exercise-instructions">Yêu cầu thêm <span class="label-muted">· Không bắt buộc</span><input v-model="instructions" placeholder="Ví dụ: thêm một câu vận dụng thực tế…" /></label>

        <div v-if="lesson.exercises.length" class="exercise-list">
          <article v-for="(item, index) in lesson.exercises" :key="index" class="exercise-item">
            <div class="exercise-number">{{ String(index + 1).padStart(2, '0') }}</div>
            <div class="exercise-body">
              <span class="difficulty-tag" :class="'difficulty-' + item.difficulty">{{ item.difficulty === 'hard' ? 'Nâng cao' : item.difficulty === 'medium' ? 'Trung bình' : 'Cơ bản' }}</span>
              <div v-if="exerciseEditMode[index]" class="exercise-question-editor">
                <textarea v-model="item.question" rows="2" aria-label="Nội dung câu hỏi" :disabled="exercisesSubmitted" @input="exerciseChangesPending = true"></textarea>
                <button type="button" class="text-button" @click="exerciseEditMode[index] = false">Xong chỉnh sửa <span>✓</span></button>
              </div>
              <div v-else class="exercise-question-display markdown-content" v-html="renderMarkdownHtml(item.question)"></div>
              <button v-if="!exerciseEditMode[index] && !exercisesSubmitted" type="button" class="text-button exercise-question-edit" @click="exerciseEditMode[index] = true">Chỉnh sửa câu hỏi <span>✎</span></button>

              <div v-if="item.choices?.length" class="choice-list" role="radiogroup" :aria-label="'Đáp án câu ' + (index + 1)">
                <label
                  v-for="(choice, choiceIndex) in item.choices"
                  :key="choiceIndex"
                  class="choice-option"
                  :class="{
                    selected: studentAnswers[index] === choice,
                    correct: exercisesSubmitted && attemptResult(index)?.correct_choice_index === choiceIndex,
                    incorrect: exercisesSubmitted && attemptResult(index)?.selected_choice_index === choiceIndex && attemptResult(index)?.correct === false
                  }"
                >
                  <input v-model="studentAnswers[index]" type="radio" :name="'exercise-' + lesson.id + '-' + index" :value="choice" :disabled="exercisesSubmitted" />
                  <span v-html="renderInlineMarkdownHtml(choice)"></span>
                  <strong v-if="exercisesSubmitted && attemptResult(index)?.correct_choice_index === choiceIndex" aria-label="Đáp án đúng">✓</strong>
                </label>
              </div>

              <label v-else class="written-answer">
                <span>Trả lời của bạn</span>
                <textarea v-model="studentAnswers[index]" rows="3" placeholder="Nhập câu trả lời…" :disabled="exercisesSubmitted"></textarea>
              </label>

              <div v-if="exercisesSubmitted && attemptResult(index)" class="quiz-feedback" :class="attemptResult(index)?.correct === true ? 'feedback-correct' : attemptResult(index)?.correct === false ? 'feedback-incorrect' : 'feedback-written'">
                <strong v-if="attemptResult(index)?.correct === true">Chính xác!</strong>
                <strong v-else-if="attemptResult(index)?.correct === false">Chưa chính xác</strong>
                <strong v-else>Đã ghi nhận câu trả lời tự luận</strong>
                <p v-if="attemptResult(index)?.correct === null">Phần tự luận chưa được chấm tự động. Hãy đối chiếu với đáp án tham khảo.</p>
                <div class="answer-reveal"><strong>Đáp án tham khảo</strong><div v-html="renderInlineMarkdownHtml(attemptResult(index)?.answer || '')"></div><small v-html="renderInlineMarkdownHtml(attemptResult(index)?.explanation || '')"></small></div>
              </div>
            </div>
          </article>

          <div v-if="exercisesSubmitted" class="exercise-result-summary">
            <strong>Kết quả của bạn</strong>
            <p v-if="currentAttempt?.objective_count">Đúng {{ correctExerciseCount }}/{{ currentAttempt.objective_count }} câu trắc nghiệm<span v-if="currentAttempt.score_percent !== null"> · {{ currentAttempt.score_percent }}%</span>.</p>
            <p v-if="currentAttempt?.written_count">{{ currentAttempt.written_count }} câu tự luận đã được ghi nhận; phần tự luận chưa được chấm tự động.</p>
          </div>
          <div class="exercise-actions">
            <button class="button button-secondary" :disabled="savingExercises || exercisesSubmitted" @click="saveExercises">{{ savingExercises ? 'Đang lưu…' : 'Lưu chỉnh sửa' }}</button>
            <div class="exercise-submit-actions">
              <button v-if="exercisesSubmitted" class="text-button" @click="clearExerciseAttempt">Làm lại <span>↻</span></button>
              <button v-else class="button button-primary" :disabled="submittingExercises || exerciseChangesPending" @click="submitExercises">{{ submittingExercises ? 'Đang nộp…' : exerciseChangesPending ? 'Lưu chỉnh sửa trước khi nộp' : 'Nộp bài' }} <span>✓</span></button>
            </div>
          </div>
        </div>
        <div v-else class="exercise-empty"><span>✳</span><p>Sẵn sàng thử sức?</p><small>Bài tập sẽ giúp bạn củng cố những gì vừa học.</small></div>
      </section>

      <section v-if="attemptHistory.length" class="surface-card lesson-attempt-history">
        <div class="subsection-title"><span class="exercise-icon">◷</span><div><span class="preview-label">LỊCH SỬ NỘP BÀI</span><h3>Các lần làm trước đây</h3></div></div>
        <details v-for="attempt in attemptHistory" :key="attempt.id" class="lesson-attempt-item">
          <summary><span>{{ formatDateTime(attempt.submitted_at) }}</span><strong v-if="attempt.objective_count">{{ attempt.correct_count }}/{{ attempt.objective_count }} câu đúng<span v-if="attempt.score_percent !== null"> · {{ attempt.score_percent }}%</span></strong><strong v-else>{{ attempt.total_questions }} câu đã nộp</strong></summary>
          <div class="attempt-result-list"><article v-for="(result, index) in attempt.results" :key="index" class="attempt-result-item">
            <strong>{{ index + 1 }}. <span v-html="renderInlineMarkdownHtml(result.question)"></span></strong><p class="attempt-response"><b>Trả lời:</b> <span v-html="renderInlineMarkdownHtml(result.response)"></span></p>
            <p v-if="result.correct !== null" :class="result.correct ? 'attempt-correct' : 'attempt-incorrect'">{{ result.correct ? 'Chính xác' : 'Chưa chính xác' }}</p>
            <p><b>Đáp án tham khảo:</b> <span v-html="renderInlineMarkdownHtml(result.answer)"></span></p><small v-html="renderInlineMarkdownHtml(result.explanation)"></small>
          </article></div>
        </details>
      </section>
    </section>
    <section v-else class="welcome-card surface-card"><div class="welcome-copy"><span class="preview-label">MỘT TRANG GIẤY CÒN TRỐNG</span><h2>Hãy bắt đầu bằng<br />một câu hỏi hay.</h2><p>Chọn môn học, viết chủ đề đang khiến bạn tò mò. Gia sư AI sẽ chuẩn bị một bài học vừa vặn.</p><RouterLink to="/history" class="text-button">Xem lại bài đã học <span>→</span></RouterLink></div><div class="welcome-art"><div class="welcome-circle"></div><div class="welcome-sun">✳</div><div class="welcome-book"><div></div><div></div></div><span class="welcome-doodle doodle-one">✦</span><span class="welcome-doodle doodle-two">✧</span><span class="welcome-note">curiosity<br />looks good<br />on you</span></div></section>
  </div>
</template>
