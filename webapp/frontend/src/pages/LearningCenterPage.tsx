import Nav from "../components/Nav";
import LearningCenter from "../learning/LearningCenter";
import LearningResources from "../learning/LearningResources";
import "../learning/learning-preview.css";

export default function LearningCenterPage() {
  return (
    <>
      <title>Learning Management Portal — FinEx Careers</title>
      <meta
        name="description"
        content="Explore FinEx Club courses, download a brochure, request enrolment and track your learning with FinEx Careers."
      />
      <Nav />
      <div className="learning-site">
        <LearningCenter>
          <LearningResources />
        </LearningCenter>
      </div>
    </>
  );
}
