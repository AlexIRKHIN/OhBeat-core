// Who is signed in. On start, a stored refresh token restores the session.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from "react";

import { api, session, type TokenPair } from "../api/client";
import type { Profile, Role } from "../api/types";

interface AuthState {
  user: Profile | null;
  loading: boolean;
  hasRole: (role: Role) => boolean;
  signIn: (pair: TokenPair) => Promise<void>;
  signOut: () => Promise<void>;
  reloadUser: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth outside AuthProvider");
  return value;
}

export const ME_QUERY = ["users", "me"] as const;

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const me = useQuery({
    queryKey: ME_QUERY,
    queryFn: () => api<Profile>("/users/me"),
    enabled: session.hasRefreshToken(),
    retry: false,
    staleTime: 60_000,
  });

  useEffect(
    () =>
      session.onExpired(() => {
        queryClient.setQueryData(ME_QUERY, null);
      }),
    [queryClient],
  );

  const signIn = useCallback(
    async (pair: TokenPair) => {
      session.setTokens(pair);
      await queryClient.fetchQuery({ queryKey: ME_QUERY, queryFn: () => api<Profile>("/users/me") });
    },
    [queryClient],
  );

  const signOut = useCallback(async () => {
    const token = session.refreshToken();
    try {
      if (token) await api<void>("/auth/logout", { method: "POST", body: { refresh_token: token } });
    } catch {
      // even if the server is unreachable, the local session ends
    }
    session.clear();
    queryClient.clear();
  }, [queryClient]);

  const reloadUser = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ME_QUERY });
  }, [queryClient]);

  const user = me.data ?? null;
  const value = useMemo<AuthState>(
    () => ({
      user,
      loading: session.hasRefreshToken() && me.isPending,
      hasRole: (role) => user?.roles.includes(role) ?? false,
      signIn,
      signOut,
      reloadUser,
    }),
    [user, me.isPending, signIn, signOut, reloadUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
