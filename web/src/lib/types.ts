export interface User {
  id: number;
  email: string;
  display_name: string;
  classroom_id: number | null;
}

export interface Classroom {
  id: number;
  name: string;
  level: string;
}

export interface Material {
  id: number;
  file_name: string;
  lesson_count: number;
  section_count: number;
  processing_status: "queued" | "processing" | "completed" | "failed" | "legacy";
  processing_progress: number;
  processing_error: string | null;
  created_at: string;
}

export interface Course {
  id: number;
  code: string;
  name: string;
  description: string;
  prompt: string;
  materials: Material[];
}

export interface CourseLessonTitle {
  id: number;
  course_id: number;
  classroom_id: number;
  title: string;
  ordinal: number;
  volume: number | null;
}

export interface CourseLessonTitleSyncResult {
  course_id: number;
  classroom_id: number;
  school_year: string;
  book_series: string;
  count: number;
  titles: CourseLessonTitle[];
}

export interface AppSettings {
  classroom_id: number | null;
  materials_removed?: number;
  material_cleanup_warning?: string;
  classes: Classroom[];
  provider: 'demo' | 'openai' | 'ollama' | 'custom';
  model: string;
  base_url: string;
  has_api_key: boolean;
  courses: Course[];
}

export interface Exercise {
  question: string;
  choices?: string[];
  answer: string;
  explanation: string;
  difficulty: string;
}

export interface ExerciseAttemptResult {
  question: string;
  choices: string[];
  answer: string;
  explanation: string;
  difficulty: string;
  response: string;
  correct: boolean | null;
  selected_choice_index: number | null;
  correct_choice_index: number | null;
}

export interface ExerciseAttempt {
  id: number;
  lesson_id: number;
  lesson_title: string;
  course_name: string;
  total_questions: number;
  objective_count: number;
  correct_count: number;
  written_count: number;
  score_percent: number | null;
  results: ExerciseAttemptResult[];
  submitted_at: string;
}

export interface Example {
  title: string;
  scenario?: string;
  steps?: string[];
  answer?: string;
}

export interface Lesson {
  id: number;
  course_id: number;
  course_name: string;
  classroom_id: number;
  classroom_name: string;
  title: string;
  content: string;
  examples: Example[];
  exercises: Exercise[];
  created_at: string;
  updated_at: string;
}

export interface LessonMessage {
  id: number;
  question: string;
  answer: string;
  created_at: string;
}
