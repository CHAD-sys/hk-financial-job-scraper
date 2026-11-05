import Nav from "../components/Nav";
import AdminOnly from "../learning/AdminOnly";
import CoursePlayer from "../learning/courses/CoursePlayer";
import "../learning/learning-preview.css";

export default function CoursePlayerPage() {
  return (
    <AdminOnly>
      <title>Course player — FinEx Learning</title>
      <meta name="robots" content="noindex" />
      <Nav />
      <div className="learning-site">
        <CoursePlayer />
      </div>
    </AdminOnly>
  );
}
