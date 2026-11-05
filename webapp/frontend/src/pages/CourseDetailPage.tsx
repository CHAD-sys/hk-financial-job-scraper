import Nav from "../components/Nav";
import AdminOnly from "../learning/AdminOnly";
import CoursePage from "../learning/courses/CoursePage";
import "../learning/learning-preview.css";

export default function CourseDetailPage() {
  return (
    <AdminOnly>
      <title>Advanced Quantitative Portfolio Management — FinEx Learning</title>
      <meta
        name="description"
        content="A six-week programme in factor investing, risk models, portfolio construction, backtesting and attribution, with interactive models, Python labs and a capstone."
      />
      <Nav />
      <div className="learning-site">
        <CoursePage />
      </div>
    </AdminOnly>
  );
}
