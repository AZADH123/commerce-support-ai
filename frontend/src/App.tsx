import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { RequireAuth, RequireReviewer } from "./components/ProtectedRoute";
import { CallbackPage } from "./features/auth/CallbackPage";
import { SignInPage } from "./features/auth/SignInPage";
import { CaseDetailPage } from "./features/cases/CaseDetailPage";
import { CaseListPage } from "./features/cases/CaseListPage";
import { ChatPage } from "./features/chat/ChatPage";
import { ReviewCasePage } from "./features/review/ReviewCasePage";
import { ReviewQueuePage } from "./features/review/ReviewQueuePage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<SignInPage />} />
      <Route path="/callback" element={<CallbackPage />} />

      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/cases" element={<CaseListPage />} />
          <Route path="/cases/:caseId" element={<CaseDetailPage />} />
        </Route>
      </Route>

      <Route element={<RequireReviewer />}>
        <Route element={<Layout />}>
          <Route path="/review" element={<ReviewQueuePage />} />
          <Route path="/review/:caseId" element={<ReviewCasePage />} />
        </Route>
      </Route>

      <Route path="/" element={<Navigate to="/chat" replace />} />
      <Route path="*" element={<Navigate to="/chat" replace />} />
    </Routes>
  );
}
