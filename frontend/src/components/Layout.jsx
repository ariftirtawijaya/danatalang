import { useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { useSettings } from "@/context/SettingsContext";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, DropdownMenuSeparator, DropdownMenuLabel } from "@/components/ui/dropdown-menu";
import {
  LayoutDashboard, Users, Wallet, FileText, ScrollText, Settings as SettingsIcon, Menu, LogOut,
  Home, PlusCircle, ClipboardList, History, User, HandCoins, BadgeCheck, Receipt, BarChart3, PiggyBank,
} from "lucide-react";

const staffNav = (role) => [
  { section: null, items: [{ to: "/dashboard", label: "Dashboard", icon: LayoutDashboard }] },
  {
    section: "Pinjaman",
    items: [
      { to: "/loans", label: "Semua Pinjaman", icon: Wallet },
      { to: "/loans?status=WAITING_ADMIN_APPROVAL", label: "Menunggu Approval", icon: ClipboardList },
      { to: "/loans?status=WAITING_FUNDING", label: "Menunggu Pendanaan", icon: HandCoins },
      { to: "/loans?status=WAITING_DISBURSEMENT_CONFIRMATION", label: "Pencairan", icon: Receipt },
      { to: "/loans?status=ACTIVE", label: "Aktif", icon: BadgeCheck },
      { to: "/loans?status=OVERDUE", label: "Terlambat", icon: FileText },
      { to: "/loans?status=PAID", label: "Lunas", icon: BadgeCheck },
    ],
  },
  {
    section: "Pengguna",
    items: [
      { to: "/borrowers", label: "Peminjam", icon: Users },
      ...(role === "superadmin"
        ? [
            { to: "/users?role=admin", label: "Admin", icon: Users },
            { to: "/users?role=lender", label: "Pendana", icon: Users },
          ]
        : [{ to: "/users?role=lender", label: "Pendana", icon: Users }]),
    ],
  },
  {
    section: "Lainnya",
    items: [
      { to: "/payments", label: "Pembayaran", icon: Receipt },
      ...(role === "superadmin"
        ? [{ to: "/profit-sharing", label: "Bagi Hasil", icon: PiggyBank }]
        : [{ to: "/earnings", label: "Penghasilan", icon: PiggyBank }]),
      { to: "/reports", label: "Laporan", icon: BarChart3 },
      ...(role === "superadmin"
        ? [
            { to: "/audit-logs", label: "Audit Log", icon: ScrollText },
            { to: "/settings", label: "Pengaturan", icon: SettingsIcon },
          ]
        : []),
    ],
  },
];

const borrowerNav = [
  { to: "/dashboard", label: "Beranda", icon: Home },
  { to: "/apply", label: "Ajukan", icon: PlusCircle },
  { to: "/my-loans", label: "Pinjaman", icon: Wallet },
  { to: "/history", label: "Riwayat", icon: History },
  { to: "/profile", label: "Profil", icon: User },
];

const lenderNav = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/available", label: "Didanai", icon: HandCoins },
  { to: "/funding", label: "Pendanaan", icon: Wallet },
  { to: "/payments", label: "Bayar", icon: Receipt },
  { to: "/settlement", label: "Bagi Hasil", icon: PiggyBank },
  { to: "/profile", label: "Profil", icon: User },
];

const Brand = ({ compact }) => {
  const { settings } = useSettings();
  return (
    <Link to="/dashboard" data-testid="brand-link" className="flex items-center gap-2.5">
      {settings?.logo_url ? (
        <img src={`${process.env.REACT_APP_BACKEND_URL}${settings.logo_url}`} alt="logo" className="h-8 w-8 rounded-lg object-cover" />
      ) : (
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary text-primary-foreground font-heading text-sm font-bold">
          {(settings?.app_name || "P").slice(0, 1)}
        </span>
      )}
      {!compact && <span className="font-heading text-base font-semibold tracking-tight">{settings?.app_name || "PinjamKu"}</span>}
    </Link>
  );
};

const UserMenu = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const roleLabel = { superadmin: "Superadmin", admin: "Admin", lender: "Pendana", borrower: "Peminjam" }[user?.role];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button data-testid="user-menu-btn" variant="ghost" className="gap-2 rounded-full px-2">
          <span className="grid h-8 w-8 place-items-center rounded-full bg-accent/20 font-heading text-xs font-semibold">
            {(user?.full_name || "?").slice(0, 1).toUpperCase()}
          </span>
          <span className="hidden text-left sm:block">
            <span className="block text-xs font-semibold leading-tight">{user?.full_name}</span>
            <span className="block text-[10px] uppercase tracking-wider text-muted-foreground">{roleLabel}</span>
          </span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuLabel className="text-xs text-muted-foreground">{user?.phone}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem data-testid="menu-profile-btn" onClick={() => navigate("/profile")}>
          <User className="mr-2 h-4 w-4" /> Profil
        </DropdownMenuItem>
        <DropdownMenuItem
          data-testid="logout-btn"
          onClick={async () => {
            await logout();
            navigate("/login");
          }}
        >
          <LogOut className="mr-2 h-4 w-4" /> Keluar
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

function SidebarNav({ role, onNavigate }) {
  const location = useLocation();
  const current = location.pathname + location.search;
  return (
    <nav className="space-y-6 px-3 py-4">
      {staffNav(role).map((group, gi) => (
        <div key={gi} className="space-y-1">
          {group.section && (
            <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">{group.section}</p>
          )}
          {group.items.map((item) => {
            const active = current === item.to || (item.to === "/loans" && current === "/loans");
            return (
              <Link
                key={item.to}
                to={item.to}
                onClick={onNavigate}
                data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, "-")}`}
                className={cn(
                  "flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm transition-colors",
                  active ? "bg-primary text-primary-foreground" : "text-foreground/80 hover:bg-muted"
                )}
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

export default function Layout({ children }) {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const isStaff = user?.role === "superadmin" || user?.role === "admin";
  const items = user?.role === "borrower" ? borrowerNav : lenderNav;

  if (isStaff) {
    return (
      <div className="min-h-screen bg-background">
        <aside className="fixed left-0 top-0 hidden h-screen w-64 flex-col border-r bg-card lg:flex">
          <div className="flex h-16 items-center border-b px-5">
            <Brand />
          </div>
          <div className="flex-1 overflow-y-auto">
            <SidebarNav role={user.role} />
          </div>
        </aside>
        <div className="lg:pl-64">
          <header className="glass sticky top-0 z-30 flex h-16 items-center justify-between gap-3 border-b px-4 sm:px-6">
            <div className="flex items-center gap-3">
              <Sheet open={open} onOpenChange={setOpen}>
                <SheetTrigger asChild>
                  <Button data-testid="mobile-menu-btn" variant="ghost" size="icon" className="lg:hidden">
                    <Menu className="h-5 w-5" />
                  </Button>
                </SheetTrigger>
                <SheetContent side="left" className="w-72 overflow-y-auto p-0">
                  <div className="flex h-16 items-center border-b px-5">
                    <Brand />
                  </div>
                  <SidebarNav role={user.role} onNavigate={() => setOpen(false)} />
                </SheetContent>
              </Sheet>
              <div className="lg:hidden">
                <Brand compact />
              </div>
            </div>
            <UserMenu />
          </header>
          <main className="mx-auto max-w-7xl px-4 py-7 sm:px-6 lg:px-8 lg:py-10">{children}</main>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="glass sticky top-0 z-30 flex h-16 items-center justify-between border-b px-4 sm:px-6">
        <Brand />
        <UserMenu />
      </header>
      <main className="mx-auto max-w-3xl px-4 pb-28 pt-6 sm:px-6 lg:max-w-5xl lg:pb-10">{children}</main>
      <nav className="glass fixed bottom-0 left-0 right-0 z-40 border-t lg:hidden" style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
        <div className="mx-auto flex max-w-md items-stretch justify-between px-2 py-1.5">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              data-testid={`bottomnav-${item.label.toLowerCase()}`}
              className={({ isActive }) =>
                cn(
                  "flex flex-1 flex-col items-center gap-1 rounded-xl px-1 py-2 text-[10px] font-medium transition-colors",
                  isActive ? "text-primary" : "text-muted-foreground"
                )
              }
            >
              {({ isActive }) => (
                <>
                  <item.icon className={cn("h-5 w-5", isActive && "scale-110")} />
                  {item.label}
                </>
              )}
            </NavLink>
          ))}
        </div>
      </nav>
      <div className="hidden lg:block">
        <div className="fixed bottom-6 left-1/2 z-40 -translate-x-1/2">
          <div className="glass flex items-center gap-1 rounded-full border px-2 py-1.5 shadow-lg">
            {items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                data-testid={`desknav-${item.label.toLowerCase()}`}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2 rounded-full px-4 py-2 text-xs font-medium transition-colors",
                    isActive ? "bg-primary text-primary-foreground" : "hover:bg-muted"
                  )
                }
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </NavLink>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
