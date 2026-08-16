import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { SettingsProvider } from "@/context/SettingsContext";
import { Toaster } from "@/components/ui/sonner";
import Layout from "@/components/Layout";
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import LoanDetail from "@/pages/LoanDetail";
import Profile from "@/pages/Profile";
import BorrowerHome from "@/pages/borrower/Home";
import BorrowerApply from "@/pages/borrower/Apply";
import BorrowerLoans from "@/pages/borrower/MyLoans";
import BorrowerHistory from "@/pages/borrower/History";
import LenderDashboard from "@/pages/lender/Dashboard";
import LenderAvailable from "@/pages/lender/Available";
import LenderFunding from "@/pages/lender/MyFunding";
import LenderPayments from "@/pages/lender/Payments";
import StaffDashboard from "@/pages/staff/Dashboard";
import StaffBorrowers from "@/pages/staff/Borrowers";
import StaffBorrowerDetail from "@/pages/staff/BorrowerDetail";
import StaffLoans from "@/pages/staff/Loans";
import StaffPayments from "@/pages/staff/Payments";
import StaffUsers from "@/pages/staff/Users";
import StaffAudit from "@/pages/staff/AuditLog";
import StaffSettings from "@/pages/staff/Settings";
import StaffReports from "@/pages/staff/Reports";
import { Skeleton } from "@/components/ui/skeleton";

const Splash = () => (
  <div className="grid min-h-screen place-items-center bg-background p-6">
    <div className="w-full max-w-sm space-y-3">
      <Skeleton className="h-10 w-40 rounded-xl" />
      <Skeleton className="h-28 w-full rounded-2xl" />
      <Skeleton className="h-28 w-full rounded-2xl" />
    </div>
  </div>
);

function Protected({ children }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Splash />;
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  return <Layout>{children}</Layout>;
}

function RoleRoutes() {
  const { user, loading } = useAuth();
  if (loading) return <Splash />;
  const role = user?.role;
  if (role === "borrower")
    return (
      <Routes>
        <Route path="/dashboard" element={<Protected><BorrowerHome /></Protected>} />
        <Route path="/apply" element={<Protected><BorrowerApply /></Protected>} />
        <Route path="/my-loans" element={<Protected><BorrowerLoans /></Protected>} />
        <Route path="/history" element={<Protected><BorrowerHistory /></Protected>} />
        <Route path="/profile" element={<Protected><Profile /></Protected>} />
        <Route path="/loans/:id" element={<Protected><LoanDetail /></Protected>} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    );
  if (role === "lender")
    return (
      <Routes>
        <Route path="/dashboard" element={<Protected><LenderDashboard /></Protected>} />
        <Route path="/available" element={<Protected><LenderAvailable /></Protected>} />
        <Route path="/funding" element={<Protected><LenderFunding /></Protected>} />
        <Route path="/payments" element={<Protected><LenderPayments /></Protected>} />
        <Route path="/profile" element={<Protected><Profile /></Protected>} />
        <Route path="/loans/:id" element={<Protected><LoanDetail /></Protected>} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    );
  if (role === "admin" || role === "superadmin")
    return (
      <Routes>
        <Route path="/dashboard" element={<Protected><StaffDashboard /></Protected>} />
        <Route path="/borrowers" element={<Protected><StaffBorrowers /></Protected>} />
        <Route path="/borrowers/:id" element={<Protected><StaffBorrowerDetail /></Protected>} />
        <Route path="/loans" element={<Protected><StaffLoans /></Protected>} />
        <Route path="/loans/:id" element={<Protected><LoanDetail /></Protected>} />
        <Route path="/payments" element={<Protected><StaffPayments /></Protected>} />
        <Route path="/users" element={<Protected><StaffUsers /></Protected>} />
        <Route path="/reports" element={<Protected><StaffReports /></Protected>} />
        <Route path="/audit-logs" element={<Protected><StaffAudit /></Protected>} />
        <Route path="/settings" element={<Protected><StaffSettings /></Protected>} />
        <Route path="/profile" element={<Protected><Profile /></Protected>} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    );
  return <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <SettingsProvider>
        <AuthProvider>
          <Toaster position="top-center" richColors />
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/*" element={<RoleRoutes />} />
          </Routes>
        </AuthProvider>
      </SettingsProvider>
    </BrowserRouter>
  );
}
