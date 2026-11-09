import { Navigate, Route, Routes } from "react-router";
import { AppLayout, RequireRole, homeOf } from "./components/Layout";
import { Spinner } from "./components/ui";
import { useAuth } from "./lib/auth";
import { ForgotPassword, Login, ResetPassword, Signup } from "./pages/auth/AuthPages";
import { AdminHome } from "./pages/admin/AdminHome";
import { DeviceCheck } from "./pages/DeviceCheck";
import { Join } from "./pages/Join";
import { ExaminerHome } from "./pages/examiner/ExaminerHome";
import { PatientDetail, Patients } from "./pages/examiner/Patients";
import { Review } from "./pages/examiner/Review";
import { TestEditor } from "./pages/examiner/TestEditor";
import { TestList } from "./pages/examiner/TestList";
import { Landing } from "./pages/Landing";
import { Onboarding } from "./pages/Onboarding";
import { PatientHome } from "./pages/patient/PatientHome";
import { PatientResult } from "./pages/patient/PatientResult";
import { StartTest } from "./pages/patient/StartTest";
import { TakeTest } from "./pages/patient/TakeTest";
import { Profile } from "./pages/Profile";

/** The landing page for visitors; signed-in people go to their own home. */
function Home() {
  const { session, me, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!session) return <Landing />;
  if (!me) return <Spinner />;
  return <Navigate to={me.role ? homeOf(me.role) : "/onboarding"} replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/onboarding" element={<Onboarding />} />
      <Route path="/join/:token" element={<Join />} />

      <Route element={<RequireRole />}>
        <Route element={<AppLayout />}>
          <Route path="/profile" element={<Profile />} />
          <Route path="/check" element={<DeviceCheck />} />
        </Route>
      </Route>

      <Route element={<RequireRole role="patient" />}>
        <Route path="/patient/test/:id" element={<TakeTest />} />
        <Route element={<AppLayout />}>
          <Route path="/patient" element={<PatientHome />} />
          <Route path="/patient/start" element={<StartTest />} />
          <Route path="/patient/results/:id" element={<PatientResult />} />
        </Route>
      </Route>

      <Route element={<RequireRole role="examiner" />}>
        <Route element={<AppLayout />}>
          <Route path="/examiner" element={<ExaminerHome />} />
          <Route path="/examiner/patients" element={<Patients />} />
          <Route path="/examiner/patients/:id" element={<PatientDetail />} />
          <Route path="/examiner/tests" element={<TestList />} />
          <Route path="/examiner/tests/new" element={<TestEditor />} />
          <Route path="/examiner/tests/:id" element={<TestEditor />} />
          <Route path="/examiner/review/:id" element={<Review />} />
        </Route>
      </Route>

      <Route element={<RequireRole role="admin" />}>
        <Route element={<AppLayout />}>
          <Route path="/admin" element={<AdminHome />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
